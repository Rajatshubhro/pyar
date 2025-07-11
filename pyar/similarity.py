import os
import math
import glob
import multiprocessing
import time
import sys
import numpy as np

# Global variable
numb_atoms = 0

Atomic_number = {
    '89': 'Ac', '13': 'Al', '95': 'Am', '51': 'Sb', '18': 'Ar', '33': 'As',
    '85': 'At', '16': 'S', '56': 'Ba', '4': 'Be', '97': 'Bk', '83': 'Bi',
    '107': 'Bh', '5': 'B', '35': 'Br', '48': 'Cd', '20': 'Ca', '98': 'Cf',
    '6': 'C', '58': 'Ce', '55': 'Cs', '17': 'Cl', '27': 'Co', '29': 'Cu',
    '24': 'Cr', '96': 'Cm', '110': 'Ds', '66': 'Dy', '105': 'Db', '99': 'Es',
    '68': 'Er', '21': 'Sc', '50': 'Sn', '38': 'Sr', '63': 'Eu', '100': 'Fm',
    '9': 'F', '15': 'P', '87': 'Fr', '64': 'Gd', '31': 'Ga', '32': 'Ge',
    '72': 'Hf', '108': 'Hs', '2': 'He', '1': 'H', '26': 'Fe', '67': 'Ho',
    '49': 'In', '53': 'I', '77': 'Ir', '70': 'Yb', '39': 'Y', '36': 'Kr',
    '57': 'La', '103': 'Lr', '3': 'Li', '71': 'Lu', '12': 'Mg', '25': 'Mn',
    '109': 'Mt', '101': 'Md', '80': 'Hg', '42': 'Mo', '60': 'Nd', '10': 'Ne',
    '93': 'Np', '41': 'Nb', '28': 'Ni', '7': 'N', '102': 'No', '79': 'Au',
    '76': 'Os', '8': 'O', '46': 'Pd', '47': 'Ag', '78': 'Pt', '82': 'Pb',
    '94': 'Pu', '84': 'Po', '19': 'K', '59': 'Pr', '61': 'Pm', '91': 'Pa',
    '88': 'Ra', '86': 'Rn', '75': 'Re', '45': 'Rh', '37': 'Rb', '44': 'Ru',
    '104': 'Rf', '62': 'Sm', '106': 'Sg', '34': 'Se', '14': 'Si', '11': 'Na',
    '81': 'Tl', '73': 'Ta', '43': 'Tc', '52': 'Te', '65': 'Tb', '22': 'Ti',
    '90': 'Th', '69': 'Tm', '112': 'Uub', '116': 'Uuh', '111': 'Uuu',
    '118': 'Uuo', '115': 'Uup', '114': 'Uuq', '117': 'Uus', '113': 'Uut',
    '92': 'U', '23': 'V', '74': 'W', '54': 'Xe', '30': 'Zn', '40': 'Zr'
}

def read_file(input_file):
    with open(input_file, "r") as file:
        return file.read().splitlines()

def Euclidean_distance(p1, p2, p3, axis_x, axis_y, axis_z):
    return math.sqrt((axis_x - p1)**2 + (axis_y - p2)**2 + (axis_z - p3)**2)

def average(data):
    return np.mean(data)

def Grigoryan_Springborg(numb_atoms, array_coord_x_1, array_coord_y_1, array_coord_z_1,
                         array_coord_x_2, array_coord_y_2, array_coord_z_2):
    distance_alpha = []
    distance_beta = []

    for i in range(numb_atoms):
        for j in range(i+1, numb_atoms):
            distance_alpha.append(Euclidean_distance(
                array_coord_x_1[i], array_coord_y_1[i], array_coord_z_1[i],
                array_coord_x_1[j], array_coord_y_1[j], array_coord_z_1[j]
            ))
            distance_beta.append(Euclidean_distance(
                array_coord_x_2[i], array_coord_y_2[i], array_coord_z_2[i],
                array_coord_x_2[j], array_coord_y_2[j], array_coord_z_2[j]
            ))

    mol_alpha = sorted(distance_alpha)
    mol_beta = sorted(distance_beta)

    num = len(mol_alpha)
    dim_alpha = average(mol_alpha)
    dim_beta = average(mol_beta)

    sumY = sum(((mol_alpha[i] / dim_alpha) - (mol_beta[i] / dim_beta))**2 for i in range(num))
    Springborg_2 = math.sqrt((2 / (numb_atoms * (numb_atoms - 1))) * sumY)

    return Springborg_2

def uniq(lst):
    seen = set()
    return [x for x in lst if not (x in seen or seen.add(x))]

def index_elements(duplicate_name, files_name):
    filtered = uniq(duplicate_name)
    return [k for u in filtered for k, v in enumerate(files_name) if v == u]

def process_files(x, array_keys, Info_Coords, threshold_duplicate, file_tmp, file_log, files_xyz):
    for y in range(x+1, len(array_keys)):
        matrix_1 = Info_Coords[array_keys[x]]
        matrix_2 = Info_Coords[array_keys[y]]

        array_name_atoms_1 = []
        array_coord_x_1 = []
        array_coord_y_1 = []
        array_coord_z_1 = []

        array_name_atoms_2 = []
        array_coord_x_2 = []
        array_coord_y_2 = []
        array_coord_z_2 = []

        for i in range(numb_atoms):
            array_tabs_1 = matrix_1[i].split()
            radii_val = Atomic_number.get(array_tabs_1[0], array_tabs_1[0])
            array_name_atoms_1.append(radii_val)
            array_coord_x_1.append(float(array_tabs_1[1]))
            array_coord_y_1.append(float(array_tabs_1[2]))
            array_coord_z_1.append(float(array_tabs_1[3]))

            array_tabs_2 = matrix_2[i].split()
            radii_val = Atomic_number.get(array_tabs_2[0], array_tabs_2[0])
            array_name_atoms_2.append(radii_val)
            array_coord_x_2.append(float(array_tabs_2[1]))
            array_coord_y_2.append(float(array_tabs_2[2]))
            array_coord_z_2.append(float(array_tabs_2[3]))

        Springborg = Grigoryan_Springborg(
            numb_atoms, array_coord_x_1, array_coord_y_1, array_coord_z_1,
            array_coord_x_2, array_coord_y_2, array_coord_z_2
        )

        if Springborg < threshold_duplicate:
            number = f"{Springborg:.6f}"
            with open(file_tmp, "a") as file:
                file.write(f"{array_keys[y]}\n")
                file.write(f"Value = {number}\n")
            with open(file_log, "a") as logfile:
                logfile.write(f"# {files_xyz[x]} ~= {files_xyz[y]}\n")
                logfile.write(f"# Value = {number}\n")
                logfile.write("------------------------\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nGrigoryan Springborg Similarity must be run with:")
        print("\nUsage:\n\tGS_Similarity.py [threshold duplicate]\n")
        sys.exit(1)

    threshold_duplicate = float(sys.argv[1])

    start_time = time.time()

    Info_Coords = {}
    array_keys = []

    files_xyz = glob.glob("./seed_00*/job*/res*.xyz")

    for i, file in enumerate(files_xyz):
        data = read_file(file)
        numb_atoms = int(data[0])
        data = data[2:]
        idx = f"{i:06d}"
        Info_Coords[idx] = data
        array_keys.append(idx)

    ncpus = multiprocessing.cpu_count()
    pool = multiprocessing.Pool(ncpus)

    file_tmp = "Dupli.tmp"
    file_log = "Info_Duplicates.txt"

    open(file_tmp, "w").close()
    with open(file_log, "w") as logfile:
        logfile.write("\n# # # SUMMARY SIMILAR STRUCTURES # # #\n\n")

    results = []
    for x in range(len(array_keys)):
        result = pool.apply_async(process_files, (x, array_keys, Info_Coords, threshold_duplicate, file_tmp, file_log, files_xyz))
        results.append(result)

    for result in results:
        result.get()

    pool.close()
    pool.join()

    with open(file_tmp, "r") as file:
        data_tmp = file.read().splitlines()

    duplicates_name = [info for info in data_tmp if "Value" not in info]
    Value_simi = [info.split()[-1] for info in data_tmp if "Value" in info]

    index_files = index_elements(duplicates_name, array_keys)

    file_xyz = "02Duplicates_coords.xyz"
    with open(file_xyz, "w") as file:
        count_sim_struc = 0
        for id_index in index_files:
            coords_dup = Info_Coords[array_keys[id_index]]
            file.write(str(len(coords_dup)) + "\n")
            file.write(f"Duplicate Structure {files_xyz[id_index]}\n")
            file.write("\n".join(coords_dup) + "\n")
            count_sim_struc += 1

    with open(file_log, "a") as logfile:
        logfile.write(f"\nNumber of Similar Structures = {count_sim_struc}\n")

    for k in index_files:
        del Info_Coords[array_keys[k]]

    file_x = "01Clean_Duplicates_coords.xyz"
    with open(file_x, "w") as file:
        for key in sorted(Info_Coords.keys()):
            new_matrix = Info_Coords[key]
            file.write(str(len(new_matrix)) + "\n")
            file.write(f"Unique Structure {files_xyz[int(key)]}\n")
            file.write("\n".join(new_matrix) + "\n")

    end_time = time.time()
    execution_time = end_time - start_time
    print(f"\n\tExecution Time: {execution_time:.2f} seconds\n")

    os.remove(file_tmp)
