'''
.. code-block::

  !---------------------------------------------------------------------------! 
  ! Interface_TorchANI: Interface between TorchANI and MLatom                 ! 
  ! Implementations by: Fuchun Ge and Max Pinheiro Jr                         ! 
  !---------------------------------------------------------------------------! 
'''

from __future__ import annotations
from typing import Any, Union, Dict, List, Callable
import os, sys, uuid
import numpy as np
import tqdm
from collections import OrderedDict
import torch
import torchani
from torchani.data import TransformableIterable, IterableAdapter

from pyar.mlatom import data
from pyar.mlatom import models
from pyar.mlatom.utils import doc_inherit

def median(yp,yt):
        return torch.median(torch.abs(yp-yt))

def molDB2ANIdata(molDB, 
                  property_to_learn=None,
                  xyz_derivative_property_to_learn=None):
    def molDBiter():
        for mol in molDB.molecules:
            ret = {'species': mol.get_element_symbols(), 'coordinates': mol.xyz_coordinates}
            if property_to_learn is not None:
                ret['energies'] = mol.__dict__[property_to_learn]
            if xyz_derivative_property_to_learn is not None:
                ret['forces'] = -1 * mol.get_xyz_vectorial_properties(xyz_derivative_property_to_learn)
            yield ret
    return TransformableIterable(IterableAdapter(lambda: molDBiter()))

class ani(models.ml_model, models.torchani_model):
    '''
    Create an `ANI <http://pubs.rsc.org/en/Content/ArticleLanding/2017/SC/C6SC05720A>`_ (`ANAKIN <https://www.google.com/search?q=Anakin+Skywalker>`_-ME: Accurate NeurAl networK engINe for Molecular Energie) model object. 
    
    Interfaces to `TorchANI <https://pubs.acs.org/doi/10.1021/acs.jcim.0c00451>`_.

    Arguments:
        model_file (str, optional): The filename that the model to be saved with or loaded from.
        device (str, optional): Indicate which device the calculation will be run on. i.e. 'cpu' for CPU, 'cuda' for Nvidia GPUs.
        hyperparameters (Dict[str, Any] | :class:`mlatom.models.hyperparameters`, optional): Updates the hyperparameters of the model with provided.
        verbose (int, optional): 0 for silence, 1 for verbosity.
    '''

    hyperparameters = models.hyperparameters({
        #### Training ####
        'batch_size':           models.hyperparameter(value=8, minval=1, maxval=1024, optimization_space='linear', dtype=int),
        'max_epochs':           models.hyperparameter(value=1000000, minval=100, maxval=1000000, optimization_space='log', dtype=int),
        'learning_rate':                    models.hyperparameter(value=0.001, minval=0.0001, maxval=0.01, optimization_space='log'),
        'early_stopping_learning_rate':     models.hyperparameter(value=1.0E-5, minval=1.0E-6, maxval=1.0E-4, optimization_space='log'),
        'lr_reduce_patience':     models.hyperparameter(value=64, minval=16, maxval=256, optimization_space='linear'),
        'lr_reduce_factor':       models.hyperparameter(value=0.5, minval=0.1, maxval=0.9, optimization_space='linear'),
        'lr_reduce_threshold':    models.hyperparameter(value=0.0, minval=-0.01, maxval=0.01, optimization_space='linear'),
        #### Loss ####
        'force_coefficient':                models.hyperparameter(value=0.1, minval=0.05, maxval=5, optimization_space='linear'),
        'median_loss':           models.hyperparameter(value=False),
        #### Network ####
        "neurons":              models.hyperparameter(value=[[160, 128, 96]]),
        # "actFun":               [["CELU", "CELU", "CELU"]],
        "fixed_layers":           models.hyperparameter(value=False),
        #### AEV ####
        'Rcr':                  models.hyperparameter(value=5.2000e+00, minval=1.0, maxval=10.0, optimization_space='linear'),
        'Rca':                  models.hyperparameter(value=3.5000e+00, minval=1.0, maxval=10.0, optimization_space='linear'),
        'EtaR':                 models.hyperparameter(value=[1.6000000e+01]),
        'ShfR':                 models.hyperparameter(value=[9.0000000e-01, 1.1687500e+00, 1.4375000e+00, 1.7062500e+00, 1.9750000e+00, 2.2437500e+00, 2.5125000e+00, 2.7812500e+00, 3.0500000e+00, 3.3187500e+00, 3.5875000e+00, 3.8562500e+00, 4.1250000e+00, 4.3937500e+00, 4.6625000e+00, 4.9312500e+00]),
        'Zeta':                 models.hyperparameter(value=[3.2000000e+01]),
        'ShfZ':                 models.hyperparameter(value=[1.9634954e-01, 5.8904862e-01, 9.8174770e-01, 1.3744468e+00, 1.7671459e+00, 2.1598449e+00, 2.5525440e+00, 2.9452431e+00]),
        'EtaA':                 models.hyperparameter(value=[8.0000000e+00]),
        'ShfA':                 models.hyperparameter(value=[9.0000000e-01, 1.5500000e+00, 2.2000000e+00, 2.8500000e+00])
    })
    
    argsdict = {}
    model_file = None
    model = None
    property_name = 'y'
    species_order = []
    program = 'TorchANI'
    meta_data = {
        "genre": "neural network"
    }
    verbose = 1

    def __init__(self, model_file: str = None, device: str = None, hyperparameters: Union[Dict[str,Any], models.hyperparameters]={}, verbose=1):
        if device == None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.device = torch.device(device)
        self.hyperparameters = self.hyperparameters.copy()
        self.hyperparameters.update(hyperparameters)
        self.verbose = verbose
        self.energy_shifter = torchani.utils.EnergyShifter(None)
        if model_file: 
            if os.path.isfile(model_file):
                self.load(model_file)
            else:
                if self.verbose: print(f'the trained ANI model will be saved in {model_file}')
            self.model_file = model_file

    def parse_args(self, args):
        super().parse_args(args)
        for hyperparam in self.hyperparameters:
            if hyperparam in args.hyperparameter_optimization['hyperparameters']:
                self.parse_hyperparameter_optimization(args, hyperparam)
            elif hyperparam in args.data:
                self.hyperparameters[hyperparam].value = args.data[hyperparam]
            elif 'ani' in args.data and hyperparam in args.ani.data:
                self.hyperparameters[hyperparam].value = args.ani.data[hyperparam]

    def reset(self):
        self.model = None


    def save(self, model_file: str = '') -> None:
        '''
        Save the model to file (.pt format).
        
        Arguments:
            model_file (str, optional): The filename that the model to be saved into. If not provided, a randomly generated string will be used.
        '''
        if not model_file:
            model_file =f'ani_{str(uuid.uuid4())}.pt'
            self.model_file = model_file
        torch.save(
            {   
                'network': self.networkdict,
                'args': self.argsdict,
                'nn': self.nn.state_dict(),
                'AEV_computer': self.aev_computer,
                'energy_shifter': self.energy_shifter,
            }
            , model_file
        )
        if self.verbose: print(f'model saved in {model_file}')

    def load(self, model_file: str = '', species_order: Union[List[str], None] = None, AEV_parameters: Union[Dict, None] = None, self_energies: Union[List[float], None] = None, reset_parameters: bool = False, method: str = '') -> None:
        '''
        Load a saved ANI model from file (.pt format).

        Arguments:
            model_file (str): The filename of the model to be loaded.
            species_order(List[str], optional): Manually provide species order if it's not present in the saved model.
            AEV_parameters(Dict, optional): Manually provide AEV parameters if it's not present in the saved model.
            self_energies(List[float], optional): Manually provide self energies if it's not present in the saved model.
            reset_parameters(bool): Reset network paramters in the loaded model.
            method(str): Load an ANI method, see also :meth:`ani.load_ani_model`.
        '''
        if method:
            self.load_ani_model(method)
            return
        
        model_dict = torch.load(model_file, map_location=torch.device('cpu'))

        if 'property' in model_dict['args']:
            self.property_name = model_dict['args']['property']

        if 'species_order' in model_dict['args']:
            self.species_order = model_dict['args']['species_order']
            # if type(self.species_order[0]) == [int, np.int_]:
            #     self.species_order = [data.atomic_number2element_symbol[z] for z in self.species_order]
            # if self.species_order[0].lower() == self.species_order[0]:
            #     self.species_order = [data.atomic_number2element_symbol[str(z)] for z in self.species_order]
        else:
            print('species order not found, please provide explictly')
            self.species_order = species_order
        self.argsdict.update({'species_order': self.species_order})

        if 'AEV_computer' in model_dict:
            self.aev_computer = model_dict['AEV_computer']
            self.argsdict.update({'Rcr': self.aev_computer.Rcr, 'Rca': self.aev_computer.Rca, 'EtaR': self.aev_computer.EtaR, 'ShfR': self.aev_computer.ShfR, 'Zeta': self.aev_computer.Zeta, 'ShfZ': self.aev_computer.ShfZ, 'EtaA': self.aev_computer.EtaA, 'ShfA': self.aev_computer.ShfA})
        elif 'Rcr' in model_dict['args']:
            self.AEV_setup(**model_dict['args'])
        else:
            print('AEV parameters not found, please provide explictly')
            self.AEV_setup(**AEV_parameters)
        
        if 'energy_shifter' in model_dict:
            self.energy_shifter = model_dict['energy_shifter']
        elif 'energy_shifter_train' in model_dict['args']:
            self.energy_shifter = model_dict['args']['energy_shifter_train']
        elif 'self_energies_train' in model_dict['args']:
            self.energy_shifter = torchani.utils.EnergyShifter(model_dict['args']['self_energies_train'])
        elif 'self_energies' in model_dict['args']:
            self.energy_shifter = torchani.utils.EnergyShifter(model_dict['args']['self_energies'])
        else:
            print('self energy information not found, please provide explictly')
            self.energy_shifter = torchani.utils.EnergyShifter(self_energies)
        self.energy_shifter.to(self.device)

        if 'network' in model_dict and 'nn' in model_dict:
            self.networkdict = model_dict['network']
            if isinstance(self.networkdict, OrderedDict) or type(self.networkdict) == dict:
                self.neurons = [[layer.out_features for layer in network if isinstance(layer, torch.nn.Linear)] for network in self.networkdict.values()]
                self.nn = torchani.ANIModel(self.networkdict if isinstance(self.networkdict, OrderedDict) else self.networkdict.values())
            elif type(self.networkdict) == list:
                self.neurons = [[[layer.out_features for layer in network if isinstance(layer, torch.nn.Linear)] for network in subdict.values()] for subdict in self.networkdict]
                self.nn = torchani.nn.Ensemble([torchani.ANIModel(subdict if isinstance(subdict, OrderedDict) else subdict.values()) for subdict in self.networkdict])
            if reset_parameters:
                self.NN_initialize()
            else:
                self.nn.load_state_dict(model_dict['nn'])
            self.optimizer_setup(**self.hyperparameters)
        else:
            print('network parameters not found')
        
        self.model = torchani.nn.Sequential(self.aev_computer, self.nn).to(self.device)
        self.model.eval()
        if self.verbose: print(f'model loaded from {model_file}')

    def load_ani_model(self, method: str, **hyperparameters) -> None:
        '''
        Load an ANI model.
        
            Arguments:
                method(str): Can be ``'ANI-1x'``, ``'ANI-1ccx'``, or ``'ANI-2x'``.
        '''
        self.hyperparameters.update(hyperparameters)
        if 'ANI-1x'.casefold() in method.casefold():
            model = torchani.models.ANI1x(periodic_table_index=True).to(self.device)
        elif 'ANI-1ccx'.casefold() in method.casefold():
            model = torchani.models.ANI1ccx(periodic_table_index=True).to(self.device)
        elif 'ANI-2x'.casefold() in method.casefold():
            model = torchani.models.ANI2x(periodic_table_index=True).to(self.device)
        else:
            print("method not found, please check ANI_methods().available_methods")
            return

        self.species_order = model.species
        self.argsdict.update({'species_order': self.species_order})
        self.aev_computer = model.aev_computer
        self.networkdict = [OrderedDict(**{k: v for k, v in nn.items()}) for nn in model.neural_networks]
        self.neurons = [[[layer.out_features for layer in network if isinstance(layer, torch.nn.Linear)] for network in subdict.values()] for subdict in self.networkdict]
        self.nn = model.neural_networks
        self.optimizer_setup(**self.hyperparameters)
        self.energy_shifter = model.energy_shifter
        self.model = torchani.nn.Sequential(self.aev_computer, self.nn).to(self.device).float()
        if self.verbose: print(f'loaded {method} model')
    
    @doc_inherit
    def train(
        self, 
        molecular_database: data.molecular_database,
        property_to_learn: str = 'energy',
        xyz_derivative_property_to_learn: str = None,
        validation_molecular_database: Union[data.molecular_database, str, None] = 'sample_from_molecular_database',
        hyperparameters: Union[Dict[str,Any], models.hyperparameters] = {},
        spliting_ratio: float = 0.8, 
        save_model: bool = True,
        check_point: str = None,
        reset_optim_state: bool = False,
        use_last_model: bool = False,
        reset_parameters: bool = False,
        reset_network: bool = False,
        reset_optimizer: bool = False,
        save_every_epoch: bool = False,
    ) -> None:
        r'''
            validation_molecular_database (:class:`mlatom.data.molecular_database` | str, optional): Explicitly defines the database for validation, or use ``'sample_from_molecular_database'`` to make it sampled from the training set.
            hyperparameters (Dict[str, Any] | :class:`mlatom.models.hyperparameters`, optional): Updates the hyperparameters of the model with provided.
            spliting_ratio (float, optional): The ratio sub-training dataset in the whole training dataset.
            save_model (bool, optional): Whether save the model to disk during training process. Note that the model might be saved many times during training.
            reset_optim_state (bool, optional): Whether to reset the state of optimizer.
            use_last_model (bool, optional): Whether to keep the ``self.model`` as it is in the last training epoch. If ``False``, the best model will be loaded to memory at the end of training.
            reset_parameters (bool, optional): Whether to reset the model's parameters before training.
            reset_network (bool, optional): Whether to re-construct the network before training.
            reset_optimizer (bool, optional): Whether to re-define the optimizer before training .
            save_every_epoch (bool, optional): Whether to save model in every epoch, valid when ``save_model`` is ``True``.
        '''
        if hyperparameters:
            self.hyperparameters.update(hyperparameters)
        
        self.data_setup(molecular_database, validation_molecular_database, spliting_ratio, property_to_learn, xyz_derivative_property_to_learn)

        if not self.model:
            self.model_setup(**self.hyperparameters)

        if reset_network:
            self.NN_setup(**self.hyperparameters)

        if reset_parameters:
            self.NN_initialize()
        
        if reset_optimizer:
            self.optimizer_setup(**self.hyperparameters)

        self.model.train()

        if check_point and os.path.isfile(check_point):
            checkpoint = torch.load(check_point)
            self.nn.load_state_dict(checkpoint['nn'])
            if not reset_optim_state:
                self.AdamW.load_state_dict(checkpoint['AdamW'])
                self.SGD.load_state_dict(checkpoint['SGD'])
                self.AdamW_scheduler.load_state_dict(checkpoint['AdamW_scheduler'])
                self.SGD_scheduler.load_state_dict(checkpoint['SGD_scheduler'])
    
        def validate():
            total_mse = 0.0
            count = 0
            for properties in self.validation_set:
                true_energies = properties['energies'].to(self.device).float()
                species = properties['species'].to(self.device)
                num_atoms = (species >= 0).sum(dim=1, dtype=true_energies.dtype)

                weightings_e = 1
                coordinates = properties['coordinates'].to(self.device).float()
                _, predicted_energies = self.model((species, coordinates))
                total_mse += loss_function(predicted_energies, true_energies, weightings_e, reduction='sum').nanmean().sqrt().item()
                count += predicted_energies.shape[0]
            return np.sqrt(total_mse/count)

        def loss_function(prediction, reference, weightings=1, reduction='none'):
            return torch.nn.functional.mse_loss(prediction*weightings, reference*weightings, reduction=reduction)

        if self.verbose: print("training starting from epoch", self.AdamW_scheduler.last_epoch + 1)
        for _ in range(self.AdamW_scheduler.last_epoch + 1, self.hyperparameters['max_epochs'].value):
            rmse = validate()
            if self.verbose: print('validation RMSE:', rmse, 'at epoch', self.AdamW_scheduler.last_epoch + 1)
            sys.stdout.flush()
            learning_rate = self.AdamW.param_groups[0]['lr']
            if self.verbose: print('learning_rate:',learning_rate)

            if learning_rate < self.hyperparameters['early_stopping_learning_rate'].value:
                break

            if self.AdamW_scheduler.is_better(rmse, self.AdamW_scheduler.best) or save_every_epoch:
                if save_model:
                    self.save(self.model_file)

            self.AdamW_scheduler.step(rmse)
            self.SGD_scheduler.step(rmse)
            for properties in tqdm.tqdm(
                self.subtraining_set,
                total=len(self.subtraining_set),
                desc="epoch {}".format(self.AdamW_scheduler.last_epoch),
                disable=not self.verbose,
            ):
                true_energies = properties['energies'].to(self.device).float()
                species = properties['species'].to(self.device)
                num_atoms = (species >= 0).sum(dim=1, dtype=true_energies.dtype)

                weightings_e = 1
                weightings_f = 1 


                if xyz_derivative_property_to_learn:
                    coordinates = properties['coordinates'].to(self.device).float().requires_grad_(True)
                    true_forces = properties['forces'].to(self.device).float()
                    _, predicted_energies = self.model((species, coordinates))
                    forces = -torch.autograd.grad(predicted_energies.sum(), coordinates, create_graph=True, retain_graph=True)[0]
                    true_energies[true_energies.isnan()]=predicted_energies[true_energies.isnan()]
                    if self.hyperparameters['median_loss'].value:
                        energy_loss= median(predicted_energies,true_energies)
                    else:
                        energy_loss = (loss_function(predicted_energies, true_energies, weightings_e) / num_atoms.sqrt()).nanmean()
                    true_forces[true_forces.isnan()]=forces[true_forces.isnan()]
                    force_loss = (loss_function(true_forces, forces, weightings_f).sum(dim=(1, 2)) / num_atoms).nanmean()
                    loss = energy_loss + self.hyperparameters['force_coefficient'].value * force_loss
                else:
                    coordinates = properties['coordinates'].to(self.device).float()
                    _, predicted_energies = self.model((species, coordinates))
                    loss = (loss_function(predicted_energies, true_energies, weightings_e) / num_atoms.sqrt()).nanmean()

                self.AdamW.zero_grad()
                self.SGD.zero_grad()
                loss.backward()
                self.AdamW.step()
                self.SGD.step()

            if check_point:
                torch.save({
                    'nn':               self.nn.state_dict(),
                    'AdamW':            self.AdamW.state_dict(),
                    'SGD':              self.SGD.state_dict(),
                    'AdamW_scheduler':  self.AdamW_scheduler.state_dict(),
                    'SGD_scheduler':    self.SGD_scheduler.state_dict(),
                }, check_point)

        if save_model and not use_last_model:
            self.load(self.model_file)

    @doc_inherit
    def predict(
            self, 
            molecular_database: data.molecular_database = None, 
            molecule: data.molecule = None,
            calculate_energy: bool = False,
            calculate_energy_gradients: bool = False, 
            calculate_hessian: bool = False,
            property_to_predict: Union[str, None] = 'estimated_y', 
            xyz_derivative_property_to_predict: Union[str, None] = None, 
            hessian_to_predict: Union[str, None] = None, 
            batch_size: int = 2**16,
        ) -> None:
        '''
            batch_size (int, optional): The batch size for batch-predictions.
        '''
        molDB, property_to_predict, xyz_derivative_property_to_predict, hessian_to_predict = \
            super().predict(molecular_database=molecular_database, molecule=molecule, calculate_energy=calculate_energy, calculate_energy_gradients=calculate_energy_gradients, calculate_hessian=calculate_hessian, property_to_predict = property_to_predict, xyz_derivative_property_to_predict = xyz_derivative_property_to_predict, hessian_to_predict = hessian_to_predict)
        
        for batch in molDB.batches(batch_size):
            for properties in molDB2ANIdata(molDB).species_to_indices(self.species_order).collate(batch_size).cache():
                species = properties['species'].to(self.device)
                xyz_coordinates = properties['coordinates'].to(self.device).float().to(self.device).requires_grad_(bool(xyz_derivative_property_to_predict or hessian_to_predict))
            ANI_NN_energies = self.energy_shifter(self.model((species, xyz_coordinates))).energies
            if property_to_predict: 
                batch.add_scalar_properties(ANI_NN_energies.detach().cpu().numpy(), property_to_predict)
            if xyz_derivative_property_to_predict or hessian_to_predict:
                ANI_NN_energy_gradients = torch.autograd.grad(ANI_NN_energies.sum(), xyz_coordinates, create_graph=True, retain_graph=True)[0]
                if xyz_derivative_property_to_predict:
                    grads = ANI_NN_energy_gradients.detach().cpu().numpy()
                    batch.add_xyz_vectorial_properties(grads, xyz_derivative_property_to_predict)
                if hessian_to_predict:
                    ANI_NN_hessians = torchani.utils.hessian(xyz_coordinates, energies=ANI_NN_energies)
                    batch.add_scalar_properties(ANI_NN_hessians.detach().cpu().numpy(), hessian_to_predict)


    def AEV_setup(self, **kwargs):
        kwargs = models.hyperparameters(kwargs)
        Rcr = kwargs['Rcr'].value
        Rca = kwargs['Rca'].value
        EtaR = torch.tensor(kwargs['EtaR'].value).to(self.device)
        ShfR = torch.tensor(kwargs['ShfR'].value).to(self.device)
        Zeta = torch.tensor(kwargs['Zeta'].value).to(self.device)
        ShfZ = torch.tensor(kwargs['ShfZ'].value).to(self.device)
        EtaA = torch.tensor(kwargs['EtaA'].value).to(self.device)
        ShfA = torch.tensor(kwargs['ShfA'].value).to(self.device)
        self.aev_computer = torchani.AEVComputer(Rcr, Rca, EtaR, ShfR, EtaA, Zeta, ShfA, ShfZ, len(self.species_order))
        self.argsdict.update({'Rcr': Rcr, 'Rca': Rca, 'EtaR': EtaR, 'ShfR': ShfR, 'Zeta': Zeta, 'ShfZ': ShfZ, 'EtaA': EtaA, 'ShfA': ShfA, 'species_order': self.species_order})

    def NN_setup(self, **kwargs):
        kwargs = models.hyperparameters(kwargs)
        if len(kwargs['neurons'].value) == 1:
            self.neurons = [kwargs['neurons'].value[0].copy() for _ in range(len(self.species_order))]

        # if len(kwargs['actFun'].value) == 1:
        #     kwargs['actFun'].value *= len(self.species_order)

        self.networkdict = OrderedDict()
        for i, specie in enumerate(self.species_order):
            self.neurons[i] += [1]
            layers = [torch.nn.Linear(self.aev_computer.aev_length, self.neurons[i][0])]
            for j in range(len(self.neurons[i]) - 1):
                layers += [torch.nn.CELU(0.1)]
                layers += [torch.nn.Linear(self.neurons[i][j], self.neurons[i][j + 1])]
            self.networkdict[specie] = torch.nn.Sequential(*layers)

        self.nn = torchani.ANIModel(self.networkdict)

        self.NN_initialize()
        self.optimizer_setup(**kwargs)  

    def NN_initialize(self, a: float = 1.0) -> None:
        '''
        Reset the network parameters using :meth:`torch.nn.init.kaiming_normal_`.

        Arguments:
            a(float): Check `torch.nn.init.kaiming_normal_() <https://pytorch.org/docs/stable/nn.init.html#torch.nn.init.kaiming_uniform_>`_.
        '''
        def init_params(m):
            if isinstance(m, torch.nn.Linear):
                torch.nn.init.kaiming_normal_(m.weight, a)
                torch.nn.init.zeros_(m.bias)

        self.nn.apply(init_params)

    def optimizer_setup(self, **kwargs):
        kwargs = models.hyperparameters(kwargs)
        if isinstance(self.networkdict, OrderedDict) or type(self.networkdict) == dict:
            wlist2d = [
                [
                    {'params': [self.networkdict[specie][j * 2].weight]} if j == 0 or j == len(self.neurons[i]) - 1 else {'params': [self.networkdict[specie][j*2].weight], 'weight_decay': 0.0001 / 10**j} for j in range(len(self.neurons[i]))
                ] for i, specie in enumerate(self.species_order)
            ]

            blist2d = [
                [
                    {'params': [self.networkdict[specie][j * 2].bias]} for j in range(len(self.neurons[i]))
                ] for i, specie in enumerate(self.species_order)
            ]
            self.AdamW = torch.optim.AdamW([i for j in wlist2d for i in j],lr=kwargs['learning_rate'].value)
            self.SGD = torch.optim.SGD([i for j in blist2d for i in j], lr=kwargs['learning_rate'].value)
        elif type(self.networkdict) == list:
            wlist3d =[[
                [
                    {'params': [subdict[specie][j * 2].weight]} if j == 0 or j == len(self.neurons[k][i]) - 1 else {'params': [subdict[specie][j*2].weight], 'weight_decay': 0.0001 / 10**j} for j in range(len(self.neurons[k][i]))
                ] for i, specie in enumerate(self.species_order)
            ] for k, subdict in enumerate(self.networkdict)]

            blist3d = [[
                [
                    {'params': [subdict[specie][j * 2].bias]} for j in range(len(self.neurons[k][i]))
                ] for i, specie in enumerate(self.species_order)
            ] for k, subdict in enumerate(self.networkdict)]

            self.AdamW = torch.optim.AdamW([i for k in wlist3d for j in k for i in j],lr=kwargs['learning_rate'].value)
            self.SGD = torch.optim.SGD([i for k in blist3d for j in k  for i in j], lr=kwargs['learning_rate'].value)
            
        self.AdamW_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(self.AdamW, factor=kwargs['lr_reduce_factor'].value, patience=kwargs['lr_reduce_patience'].value, threshold=kwargs['lr_reduce_threshold'].value)
        self.SGD_scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(self.SGD, factor=kwargs['lr_reduce_factor'].value, patience=kwargs['lr_reduce_patience'].value, threshold=kwargs['lr_reduce_threshold'].value)

    def model_setup(self, **kwargs):
        self.AEV_setup(**kwargs)
        self.NN_setup(**kwargs)
        self.model = torchani.nn.Sequential(self.aev_computer, self.nn).to(self.device)

    def fix_layers(self, layers_to_fix: Union[List[List[int]],List[int]]):
        '''
        Fix specific layers to be non-trainable for each element.

        Arguments:
            layers_to_fix (List): Should be: 
            
                - A list of integers. Layers indicate by the integers will be fixed
                - A list of lists of integers. Each sub-list defines the layers to be fixed for each species, in the order of `self.species_order`. 
        '''
        if layers_to_fix:
            if len(layers_to_fix) == 1:
                layers_to_fix = layers_to_fix * len(self.species_order)
            for name, parameter in self.model.named_parameters():
                indices = name.split('.')
                if int(indices[-2]) in layers_to_fix[self.species_order.index(indices[-3] if indices[-3] in data.element_symbol2atomic_number else data.atomic_number2element_symbol[int(indices[-3])])]:
                    parameter.requires_grad=False

    def data_setup(self, molecular_database, validation_molecular_database, spliting_ratio,
                   property_to_learn, xyz_derivative_property_to_learn, ):
        assert molecular_database, 'provide molecular database'

        self.property_name = property_to_learn
        
        data_element_symbols = list(np.sort(np.unique(molecular_database.get_element_symbols())))

        if not self.species_order: 
            self.species_order = data_element_symbols
        else:
            for element in data_element_symbols:
                if element not in self.species_order:
                    print('element(s) outside supported species detected, please check the database')
                    return
                
        if validation_molecular_database == 'sample_from_molecular_database':
            idx = np.arange(len(molecular_database))
            np.random.shuffle(idx)
            molecular_database, validation_molecular_database = [molecular_database[i_split] for i_split in np.split(idx, [int(len(idx) * spliting_ratio)])]
        elif not validation_molecular_database:
            raise NotImplementedError("please specify validation_molecular_database or set it to 'sample_from_molecular_database'")

        if self.energy_shifter.self_energies is None:
            if np.isnan(molecular_database.get_properties(property_to_learn)).sum():
                molDB2ANIdata(molecular_database.filter_by_property(property_to_learn), property_to_learn, xyz_derivative_property_to_learn).subtract_self_energies(self.energy_shifter, self.species_order)
                self.subtraining_set = molDB2ANIdata(molecular_database, property_to_learn, xyz_derivative_property_to_learn).species_to_indices(self.species_order).subtract_self_energies(self.energy_shifter.self_energies).shuffle()
            else:   
                self.subtraining_set = molDB2ANIdata(molecular_database, property_to_learn, xyz_derivative_property_to_learn).subtract_self_energies(self.energy_shifter, self.species_order).species_to_indices(self.species_order).shuffle()
        else:
            self.subtraining_set = molDB2ANIdata(molecular_database, property_to_learn, xyz_derivative_property_to_learn).species_to_indices(self.species_order).subtract_self_energies(self.energy_shifter.self_energies).shuffle()
        self.validation_set = molDB2ANIdata(validation_molecular_database, property_to_learn, xyz_derivative_property_to_learn).species_to_indices(self.species_order).subtract_self_energies(self.energy_shifter.self_energies).shuffle()
        
        self.energy_shifter = self.energy_shifter.to(self.device)
        
        self.subtraining_set = self.subtraining_set.collate(self.hyperparameters['batch_size'].value).cache()
        self.validation_set = self.validation_set.collate(self.hyperparameters['batch_size'].value).cache()

        self.argsdict.update({'self_energies': self.energy_shifter.self_energies, 'property': self.property_name})

class ani_child(models.torchani_model):
    def __init__(self, parent, index, device='cuda' if torch.cuda.is_available() else 'cpu'):
        self.device = torch.device(device)
        self.model = parent.__getitem__(index)

    def predict(self, molecular_database=None, molecule=None,
                calculate_energy=True, calculate_energy_gradients=False, calculate_hessian=False, batch_size=1024):
        molDB = super().predict(molecular_database=molecular_database, molecule=molecule)

        for mol in molDB.molecules:
            species = torch.tensor([atom.atomic_number for atom in mol.atoms]).to(self.device).unsqueeze(0)
            xyz_coordinates = torch.tensor(mol.xyz_coordinates).double().to(self.device).requires_grad_(calculate_energy_gradients or calculate_hessian).unsqueeze(0)
            ANI_NN_energy = self.model((species, xyz_coordinates)).energies
            if calculate_energy: mol.energy = float(ANI_NN_energy)
            if calculate_energy_gradients or calculate_hessian:
                ANI_NN_energy_gradients = torch.autograd.grad(ANI_NN_energy.sum(), xyz_coordinates, create_graph=True, retain_graph=True)[0]
                if calculate_energy_gradients:
                    grads = ANI_NN_energy_gradients[0].detach().cpu().numpy()
                    for iatom in range(len(mol.atoms)):
                        mol.atoms[iatom].energy_gradients = grads[iatom]
            if calculate_hessian:
                ANI_NN_hessian = torchani.utils.hessian(xyz_coordinates, energies=ANI_NN_energy)
                mol.hessian = ANI_NN_hessian[0].detach().cpu().numpy()
    
    def node(self, name):
        return models.model_tree_node(name=name, operator='predict', model=self)
    
class ani_methods(models.torchani_model):
    '''
    Creat a model object with on of the ANI methods

    Arguments:
        method (str): A string that specifies the method. Available choices: ``'ANI-1x'``, ``'ANI-1ccx'``, or ``'ANI-2x'``.
        device (str, optional): Indicate which device the calculation will be run on. i.e. 'cpu' for CPU, 'cuda' for Nvidia GPUs.

    '''
    available_methods = models.methods.methods_map['ani']
    atomic_energies = {'ANI-1ccx': {1:-0.50088088, 6:-37.79199048, 7:-54.53379230, 8:-75.00968205}}

    def __init__(self, method: str = 'ANI-1ccx', device: str = 'cuda' if torch.cuda.is_available() else 'cpu', **kwargs):
        self.device = torch.device(device)
        self.model_setup(method)
        modelname = method.lower().replace('-','')
        self.children = [ani_child(self.model, index, device=device).node(f'{modelname}_nn{index}') for index in range(len(self.model))]
        if 'D4'.casefold() in self.method.casefold():
            d4 = models.model_tree_node(name='d4_wb97x', operator='predict', model=models.methods(method='D4', functional='wb97x'))
            ani_nns = models.model_tree_node(name=f'{modelname}_nn', children=self.children, operator='average')
            self.model = models.model_tree_node(name=modelname, children=[ani_nns, d4], operator='sum')
        else:
            self.model = models.model_tree_node(name=modelname, children=self.children, operator='average')

    def model_setup(self, method):
        self.method = method
        if 'ANI-1x'.casefold() in method.casefold():
            self.model = torchani.models.ANI1x(periodic_table_index=True).to(self.device).double()
            self.atomic_number_available = [1, 6, 7, 8]     
        elif 'ANI-1ccx'.casefold() in method.casefold():
            self.model = torchani.models.ANI1ccx(periodic_table_index=True).to(self.device).double()
            self.atomic_number_available = [1, 6, 7, 8]          
        elif 'ANI-2x'.casefold() in method.casefold():
            self.model = torchani.models.ANI2x(periodic_table_index=True).to(self.device).double()
            self.atomic_number_available = [1, 6, 7, 8, 9, 16, 17]
        else:
            print("method not found, please check ANI_methods().available_methods")
            
    @doc_inherit
    def predict(self, molecular_database=None, molecule=None, calculate_energy=True, calculate_energy_gradients=False, calculate_hessian=False):
        molDB = super().predict(molecular_database=molecular_database, molecule=molecule)

        for mol in molDB.molecules:
            self.predict_for_molecule(molecule=mol,
                                    calculate_energy=calculate_energy, calculate_energy_gradients=calculate_energy_gradients, calculate_hessian=calculate_hessian)
        
    def predict_for_molecule(self, molecule=None,
                calculate_energy=True, calculate_energy_gradients=False, calculate_hessian=False):
        
        for atom in molecule.atoms:
            if not atom.atomic_number in self.atomic_number_available:
                print(f' * Warning * Molecule contains elements other than {"C/H/N/O/F/S/Cl" if "ANI-2x".casefold() in self.method.casefold() else "CHNO"}, no calculations performed')
                return
        
        if len(molecule.atoms) == 1:
            molecule.energy = self.atomic_energies[self.method][molecule.atoms[0].atomic_number]
            
        else:
            self.model.predict(molecule=molecule,
                               calculate_energy=calculate_energy,
                               calculate_energy_gradients=calculate_energy_gradients, 
                               calculate_hessian=calculate_hessian)
            
            properties = [] ; atomic_properties = []
            if calculate_energy: properties.append('energy')
            if calculate_energy_gradients: atomic_properties.append('energy_gradients')
            if calculate_hessian: properties.append('hessian')
            if 'D4'.casefold() in self.method.casefold():
                modelname = self.method.lower().replace('-','')
                modelname = f'{modelname}_nn'
            else:
                modelname = self.method.lower().replace('-','')
            molecule.__dict__[f'{modelname}'].standard_deviation(properties=properties+atomic_properties)

def printHelp():
    helpText = __doc__.replace('.. code-block::\n\n', '') + '''
  To use Interface_ANI, please install TorchANI and its dependencies

  Arguments with their default values:
    MLprog=TorchANI            enables this interface
    MLmodelType=ANI            requests ANI model

    ani.batch_size=8           batch size
    ani.max_epochs=10000000    max epochs
    ani.learning_rate=0.001    learning rate used in the Adam and SGD optimizers
    
    ani.early_stopping_learning_rate=0.00001
                               learning rate that triggers early-stopping
    
    ani.force_coefficient=0.1  weight for force
    ani.Rcr=5.2                radial cutoff radius
    ani.Rca=3.5                angular cutoff radius
    ani.EtaR=1.6               radial smoothness in radial part
    
    ani.ShfR=0.9,1.16875,      radial shifts in radial part
      1.4375,1.70625,1.975,
      2.24375,2.5125,2.78125,
      3.05,3.31875,3.5875,
      3.85625,4.125,4.9375,
      4.6625,4.93125
    
    ani.Zeta=32                angular smoothness
    
    ani.ShfZ=0.19634954,       angular shifts
      0.58904862,0.9817477,
      1.3744468,1.7671459,
      2.1598449,2.552544,
      2.9452431
    
    ani.EtaA=8                 radial smoothness in angular part
    ani.ShfA=0.9,1.55,2.2,2.85 radial shifts in angular part

  Cite TorchANI:
    X. Gao, F. Ramezanghorbani, O. Isayev, J. S. Smith, A. E. Roitberg,
    J. Chem. Inf. Model. 2020, 60, 3408
    
  Cite ANI model:
    J. S. Smith, O. Isayev, A. E. Roitberg, Chem. Sci. 2017, 8, 3192
'''
    print(helpText)
