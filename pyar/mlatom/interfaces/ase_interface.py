#!/usr/bin/env python3
'''
  !---------------------------------------------------------------------------! 
  ! ase: interface to the ASE package                                         ! 
  ! Implementations by: Peikung Zheng and Pavlo O. Dral                       ! 
  !---------------------------------------------------------------------------! 
'''
import numpy as np
import copy, tempfile
import warnings
warnings.filterwarnings("ignore")
from pyar.mlatom import constants
from pyar.mlatom import data
from pyar.mlatom import stopper
    
try:
    import ase
    from ase import io
    from ase.calculators.calculator import Calculator, all_changes
    from ase.thermochemistry import IdealGasThermo
    import ase.units as units
except:
    raise ValueError('ASE is not installed')

def optimize_geometry(initial_molecule, model, convergence_criterion_for_forces, maximum_number_of_steps, optimization_algorithm='LBFGS'):
    if optimization_algorithm == None:
        optimization_algorithm = 'LBFGS'
    
    optimization_trajectory = data.molecular_trajectory()
    globals()['initial_molecule'] = initial_molecule
    globals()['optimization_trajectory'] = optimization_trajectory
    
    # Ugly solution because no time to understand what 'atoms' in ASE is exactly (probably corresponds to MLatom's 'molecular_database')
    # more like 'molecule', the 'atoms' object defines a collection of atoms
    with tempfile.TemporaryDirectory() as tmpdirname: # todo: new atoms object directly, with something like molecule.ase()
        xyzfilename = f'{tmpdirname}/tmp.xyz'
        initial_molecule.write_file_with_xyz_coordinates(filename=xyzfilename)
        atoms = io.read(xyzfilename, index=':', format='xyz')[0]
    # atoms.set_calculator(MLatomCalculator(model=model, save_optimization_trajectory=True))
    # atoms.set_calculator() is deprecated
    atoms.calc = MLatomCalculator(model=model, save_optimization_trajectory=True)
    
    from ase import optimize
    opt = optimize.__dict__[optimization_algorithm](atoms)
    opt.run(fmax=convergence_criterion_for_forces, steps=maximum_number_of_steps)
    
    return optimization_trajectory

def transition_state(initial_molecule, model, 
                     convergence_criterion_for_forces,
                     maximum_number_of_steps,  
                     optimization_algorithm='dimer', **kwargs):
    if optimization_algorithm.casefold() == 'dimer'.casefold():
        return dimer_method(initial_molecule, model, 
                            convergence_criterion_for_forces,
                            maximum_number_of_steps,  **kwargs)
    elif optimization_algorithm.casefold() == 'NEB'.casefold():
        return nudged_elastic_band(initial_molecule, model, 
                            convergence_criterion_for_forces,
                            maximum_number_of_steps,  **kwargs)

def dimer_method(initial_molecule, model, 
                 convergence_criterion_for_forces,
                 maximum_number_of_steps,  **kwargs):
    optimization_trajectory = data.molecular_trajectory()
    globals()['initial_molecule'] = initial_molecule
    globals()['optimization_trajectory'] = optimization_trajectory

    with tempfile.TemporaryDirectory() as tmpdirname: # todo: new atoms object directly
        xyzfilename = f'{tmpdirname}/tmp.xyz'
        initial_molecule.write_file_with_xyz_coordinates(filename=xyzfilename)
        atoms = io.read(xyzfilename, index=':', format='xyz')[0]

    atoms.calc = MLatomCalculator(model=model, save_optimization_trajectory=True)

    from ase.dimer import DimerControl, MinModeAtoms, MinModeTranslate

    with DimerControl(**kwargs) as d_control:
        d_atoms = MinModeAtoms(atoms, d_control)
        d_atoms.displace()
        with MinModeTranslate(d_atoms) as dim_rlx:
            dim_rlx.run(fmax=convergence_criterion_for_forces,
                        steps=maximum_number_of_steps)
    
    return optimization_trajectory

def nudged_elastic_band(initial_molecule, final_molecule, model, 
                        convergence_criterion_for_forces,
                        maximum_number_of_steps,
                        number_of_middle_images=3, **kwargs):
    optimization_trajectory = data.molecular_trajectory()
    globals()['initial_molecule'] = initial_molecule
    globals()['optimization_trajectory'] = optimization_trajectory

    with tempfile.TemporaryDirectory() as tmpdirname: # todo: new atoms object directly
        xyzfilename = f'{tmpdirname}/tmp_init.xyz'
        initial_molecule.write_file_with_xyz_coordinates(filename=xyzfilename)
        initial = io.read(xyzfilename, index=':', format='xyz')[0]
        xyzfilename = f'{tmpdirname}/tmp_final.xyz'
        final_molecule.write_file_with_xyz_coordinates(filename=xyzfilename)
        final = io.read(xyzfilename, index=':', format='xyz')[0]

    from ase.neb import NEB
    from ase.optimize import MDMin
    images = [initial]
    images += [initial.copy() for i in range(number_of_middle_images)]
    images += [final]
    neb = NEB(images)
    neb.interpolate()
    for image in images[1:number_of_middle_images+1]:
        image.calc = MLatomCalculator(model=model, save_optimization_trajectory=True)
    optimizer = MDMin(neb, trajectory='A2B.traj')
    optimizer.run(fmax=maximum_number_of_steps,
                  steps=maximum_number_of_steps)


class MLatomCalculator(Calculator):
    implemented_properties = ['energy', 'forces']
    def __init__(self, model, save_optimization_trajectory = False):
        super(MLatomCalculator, self).__init__()
        self.model = model
        self.save_optimization_trajectory = save_optimization_trajectory

    def calculate(self, atoms=None, properties=['energy'], system_changes=all_changes):
        super(MLatomCalculator, self).calculate(atoms, properties, system_changes)
        global initial_molecule
        # Ugly solution because no time to understand what 'atoms' in ASE is exactly (probably corresponds to MLatom's 'molecular_database')
        with tempfile.TemporaryDirectory() as tmpdirname:
            xyzfilename = f'{tmpdirname}/tmp.xyz'
            io.write(xyzfilename, self.atoms, format='extxyz', plain=True)
            
            current_molecule = initial_molecule.copy()
            mol_from_file = data.molecule()
            mol_from_file.read_from_xyz_file(filename=xyzfilename)
            coordinates = mol_from_file.xyz_coordinates
            current_molecule.xyz_coordinates = coordinates
            
            self.model.predict(molecule=current_molecule, calculate_energy=True, calculate_energy_gradients=True)
            if not 'energy' in current_molecule.__dict__:
                pythonpackage = True # or False, depending on your use case
                if pythonpackage: 
                    raise ValueError('model did not return any energy')
                else: stopper.stopMLatom('model did not return any energy')
            
            if self.save_optimization_trajectory:
                global optimization_trajectory
                istep = len(optimization_trajectory.steps)
                optimization_trajectory.steps.append(data.molecular_trajectory_step(step=istep, molecule=current_molecule))
            
            energy = current_molecule.energy
            forces = -current_molecule.get_energy_gradients()

            energy *= ase.units.Hartree
            forces *= ase.units.Hartree

            self.results['energy'] = energy

            if 'forces' in properties:
                self.results['forces'] = forces

def thermochemistry(molecule):
    energy = molecule.energy * units.Hartree
    cm2ev = 100.0 * units._c * units._hplanck / units._e
    ev2kcal = units.mol / units.kcal
    freqs = copy.deepcopy(molecule.frequencies)
    if 'shape' not in molecule.__dict__.keys():
        molecule.shape = 'nonlinear'
    if molecule.shape.lower() == 'linear': add_freqs = np.zeros(5)
    else: add_freqs = np.zeros(6)
    freqs = np.array(list(add_freqs) + list(freqs)).astype(float)
    vib_energies = freqs * cm2ev
    geometry = 'nonlinear'
    if molecule.shape.lower() == 'linear': geometry = 'linear'
    spin = (molecule.multiplicity - 1) / 2
    
    # Ugly solution because no time to understand what 'atoms' in ASE is exactly (probably corresponds to MLatom's 'molecular_database')
    with tempfile.TemporaryDirectory() as tmpdirname:
        xyzfilename = f'{tmpdirname}/tmp.xyz'
        molecule.write_file_with_xyz_coordinates(filename=xyzfilename)
        mol = io.read(xyzfilename, index=':', format='xyz')[0]
    
    if molecule.frequencies[0] > 0:
        if 'symmetry_number' not in molecule.__dict__.keys():
            molecule.symmetry_number = 1
        thermo = IdealGasThermo(vib_energies=vib_energies,
                                potentialenergy=energy,
                                atoms=mol,
                                geometry=geometry,
                                symmetrynumber=molecule.symmetry_number,
                                spin=spin)
        
        molecule.G = thermo.get_gibbs_energy(temperature=298.15, pressure=101325.) * ev2kcal * constants.kcalpermol2Hartree
        molecule.H = thermo.get_enthalpy(temperature=298.15, verbose=True) * ev2kcal * constants.kcalpermol2Hartree
        molecule.H0 = thermo.get_enthalpy(temperature=0.0, verbose=True) * ev2kcal * constants.kcalpermol2Hartree
        molecule.U0 = molecule.H0
        molecule.ZPE = thermo.get_ZPE_correction() * ev2kcal * constants.kcalpermol2Hartree
    else:
        print(' * Warning * The first frequency is negative, thermochemical properties not calculated')
    