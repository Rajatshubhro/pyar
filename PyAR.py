#!/usr/bin/env python3
import argparse
import datetime
import logging
import os
import sys
import time

import numpy as np

import Molecule
import aggregator
import optimiser
import reactor
import tabu

logger = logging.getLogger('pyar')
handler = logging.FileHandler('pyar.log', 'w')


def write_csv_file(csv_filename, energy_dict):
    import csv
    with open(csv_filename, 'w') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["Name", "Energy"])
        writer.writerows(energy_dict.items())


def argument_parse():
    """ Parse command line arguments"""
    parser = argparse.ArgumentParser(prog='PyAR', description='is a \
             program to predict aggregation, reaction, clustering.  \
             There are also modules for strochastic generation of  \
             orientations of two more molecules and atoms')
    parser.add_argument("input_files", metavar='files',
                        type=str, nargs='+',
                        help='input coordinate files')
    parser.add_argument("-N", dest='hm_orientations',
                        help='how many orientations to be used')

    parser.add_argument('--site', type=int, nargs=2,
                        help='atom for site specific '
                             'aggregation/solvation')

    run_type_group = parser.add_mutually_exclusive_group(required=True)
    run_type_group.add_argument("-r", "--react",
                                help="Run a reactor calculation",
                                action='store_true')
    run_type_group.add_argument("-a", "--aggregate",
                                help="Run a aggregator calculation",
                                action='store_true')
    run_type_group.add_argument("-o", "--optimize",
                                help="Optimize the molecules",
                                action='store_true')
    run_type_group.add_argument("-mb", "--makebond", nargs=2, type=int,
                                help="make bonds between the given atoms of two"
                                     "fragments")

    aggregator_group = parser.add_argument_group('aggregator',
                                                 'Aggregator specific option')
    aggregator_group.add_argument('-as', '--aggregate-size', type=int,
                                  help='number of monomers in aggregate')

    reactor_group = parser.add_argument_group('reactor',
                                              'Reactor specific option')
    reactor_group.add_argument('-gmin', type=float,
                               help='minimum value of gamma')
    reactor_group.add_argument('-gmax', type=float,
                               help='maximum value of gamma')

    optimizer_group = parser.add_argument_group('optimizer',
                                                'Optimizer specific option')
    optimizer_group.add_argument('-gamma', type=float,
                                 help='value of gamma')

    chemistry_group = parser.add_argument_group('chemistry', 'Options related\
                                           to model chemistry')
    chemistry_group.add_argument("-c", "--charge", type=int, default=0,
                                 help="Charge of the system")
    chemistry_group.add_argument("-m", "--multiplicity", type=int,
                                 default=1, help="Multiplicity of the system")
    chemistry_group.add_argument("--scftype", type=str, choices=['rhf', 'uhf'],
                                 default='rhf',
                                 help="specify rhf or uhf (defulat=rhf)")
    chemistry_group.add_argument("--software", type=str,
                                 choices=['turbomole', 'obabel', 'mopac',
                                          'xtb', 'xtb_turbo', 'orca', 'psi4'],
                                 required=True, help="Software")
    parser.add_argument('-v', '--verbosity', default=1,
                        choices=[0, 1, 2, 3, 4], type=int,
                        help="increase output verbosity (0=Debug; 1=Info; "
                             "2: Warning; 3: Error; 4: Critical)")

    return parser.parse_args()


def setup_molecules(input_files):
    molecules = []
    for each_file in input_files:
        try:
            mol = Molecule.Molecule.from_xyz(each_file)
            logger.info(each_file)
            molecules.append(mol)
        except IOError:
            logger.critical("File {} does not exist".format(each_file))
            sys.exit()
    logger.info("I've parsed these molecules as input: {}".format(
        [i.name for i in molecules]))
    return molecules


def main():
    args = argument_parse()
    if args.verbosity == 0:
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(name)-12s %(filename)s %(funcName)s '
                                      '%(lineno)d %(levelname)-8s: %(message)s')
    elif args.verbosity == 1:
        formatter = logging.Formatter('%(message)s')
        logger.setLevel(logging.INFO)
    elif args.verbosity == 2:
        formatter = logging.Formatter('%(message)s')
        logger.setLevel(logging.WARNING)
    elif args.verbosity == 3:
        formatter = logging.Formatter('%(message)s')
        logger.setLevel(logging.ERROR)
    elif args.verbosity == 4:
        formatter = logging.Formatter('%(message)s')
        logger.setLevel(logging.CRITICAL)
    else:
        formatter = logging.Formatter('%(message)s')
        logger.setLevel(logging.CRITICAL)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.info('Starting PyAR at %s in %s' % (datetime.datetime.now(),
                                               os.getcwd()))
    logger.debug('Logging level is %d' % args.verbosity)
    logger.debug('Parsed arguments %s' % args)

    method_args = {
        'charge': args.charge,
        'multiplicity': args.multiplicity,
        'scftype': args.scftype,
        'software': args.software
    }

    logger.info('Charge:        %s' % method_args['charge'])
    logger.info('Multiplicity:  %s' % method_args['multiplicity'])
    logger.info('SCF Type:      %s' % method_args['scftype'])

    logger.info('QM Software:  %s' % method_args['software'])

    how_many_orientations = args.hm_orientations
    logger.info('%s orientations will be used' % how_many_orientations)

    input_molecules = setup_molecules(args.input_files)

    if args.site is None:
        site = None
        proximity_factor = 2.3
    else:
        site = args.site
        proximity_factor = 2.3

    if args.aggregate:
        size_of_aggregate = args.aggregate_size
        if size_of_aggregate is None:
            logger.error('For an Aggregation run '
                         'specify the aggregate size '
                         '(number of monomers to be added) '
                         'using the argument\n -as <integer>')
            sys.exit('Missing arguments: -as #')

        if how_many_orientations is None:
            logger.error("For aggregation, specify how many orientations"
                         "are to be used, by the argument\n"
                         "-number_of_orientations <number of orientations>")
            sys.exit('Missing arguments: -N #')

        if len(input_molecules) == 1:
            print('Provide at least two files')
            sys.exit('Missing arguments: Provide at least two files')
        else:
            monomer = input_molecules[-1]
            seeds = input_molecules[:-1]

        t1 = time.clock()
        aggregator.aggregate(seeds, monomer,
                             aggregate_size=size_of_aggregate,
                             hm_orientations=how_many_orientations,
                             method=method_args)

        logger.info('Total Time: {}'.format(time.clock() - t1))

    if args.react:
        minimum_gamma = args.gmin
        maximum_gamma = args.gmax
        if len(input_molecules) == 1:
            logger.error('Reactor requires at least two molecules')
            sys.exit('Missing arguments: provide at least two molecules')
        if minimum_gamma is None or maximum_gamma is None:
            logger.error('For a Reactor run specify the '
                         'values of gamma_min and gamma_max using \n'
                         '-gmin <integer> -gmax <integer>')
            sys.exit('missing arguments: -gmin <integer> -gmax <integer>')
        if how_many_orientations is None:
            logger.error("For reaction, specify how many orientations"
                         "are to be used, by the argument\n"
                         "-number_of_orientations <number of orientations>")
            sys.exit('Missing argumetns: -N #')

        if site is not None:
            site = [site[0], input_molecules[0].number_of_atoms + site[1]]
        t1 = time.clock()
        number_of_orientations = int(how_many_orientations)
        reactor.react(input_molecules[0], input_molecules[1],
                      gamma_min=minimum_gamma, gamma_max=maximum_gamma,
                      hm_orientations=number_of_orientations,
                      method=method_args,
                      site=site, proximity_factor=proximity_factor)
        logger.info('Total run time: {}'.format(time.clock() - t1))
        return

    if args.optimize:
        if args.gamma:
            gamma = args.gamma
        else:
            gamma = 0.0

        list_of_optimized_molecules = optimiser.bulk_optimize(input_molecules,
                                                              method_args,
                                                              gamma)
        if len(list_of_optimized_molecules) == 0:
            print('no optimized molecules')
        energy_dict = {n.name: n.energy for n in input_molecules}
        write_csv_file('energy.csv', energy_dict)
        from data_analysis import clustering
        clustering_results = clustering.choose_geometries(
            list_of_optimized_molecules)
        logger.info(clustering_results)

    if args.makebond:
        a = args.makebond[0]
        b = input_molecules[0].number_of_atoms + args.makebond[1]
        if how_many_orientations is None:
            logger.error("For aggregation, specify how many orientations"
                         "are    to be used, by the argument\n"
                         "-N <number of orientations>")
            sys.exit('Missing arguments: -N #')

        molecules = tabu.generate_guess_for_bonding('abc', input_molecules[0],
                                                    input_molecules[1], a, b,
                                                    int(number_of_orientations))
        for each_molecule in molecules:
            coordinates = each_molecule.coordinates
            start_dist = np.linalg.norm(coordinates[a] - coordinates[b])
            final_distance = each_molecule.covalent_radius[a] + \
                             each_molecule.covalent_radius[b]
            step = int(abs(final_distance - start_dist) * 10)
            if args.software == 'orca':
                c_k = '\n!ScanTS\n% geom scan B ' + str(a) + ' ' + str(b) +\
                      '= ' + str(start_dist) + ', ' + str(final_distance) + \
                      ', ' + str(step) + ' end end\n'

                optimiser.optimise(each_molecule, method_args, 0.0,
                                   custom_keyword=c_k)
            else:
                print(
                    'Optimization with %s is not implemented yet' % args.software)


if __name__ == "__main__":
    main()
