import re
import datetime
import numpy as np

from ase.atoms import Atoms
from ase.utils import basestring
from ase.geometry import cellpar_to_cell

__all__ = ['read_rmc6f', 'write_rmc6f']

ncols2style = {9: 'no_labels',
               10: 'labels',
               11: 'magnetic'}


def _read_construct_regex(lines):
    """
    Utility for constructing  regular expressions used by reader.
    """
    lines_re = '|'.join(lines)
    lines_re = lines_re.replace(' ', r'\s+')
    lines_re = lines_re.replace('(', r'\(')
    lines_re = lines_re.replace(')', r'\)')
    return '({})'.format(lines_re)


def _read_line_of_atoms_section(fields):
    """
    Process `fields` line of Atoms section in rmc6f file and output extracted
    info as atom id (key) and list of properties for Atoms object (values).

    Parameters
    ----------
    fields: list[str]
        List of columns from line in rmc6f file.


    Returns
    ------
    atom_id: int
        Atom ID
    properties: list[str|float]
        List of Atoms properties based on rmc6f style.
        Basically, have 1) element and fractional coordinates for 'labels'
        or 'no_labels' style and 2) same for 'magnetic' style except adds
        the spin.
        Examples for 1) 'labels' or 'no_labels' styles or 2) 'magnetic' style:
            1) [element, xf, yf, zf]
            2) [element, xf, yf, zf, spin]
    """
    # Atom id
    atom_id = int(fields[0])

    # Get style used for rmc6f from file based on number of columns
    ncols = len(fields)
    style = ncols2style[ncols]

    # Create the position dictionary
    properties = list()
    element = str(fields[1])
    if style == 'no_labels':
        # id element xf yf zf ref_num ucell_x ucell_y ucell_z
        xf = float(fields[2])
        yf = float(fields[3])
        zf = float(fields[4])
        properties = [element, xf, yf, zf]

    elif style == 'labels':
        # id element label xf yf zf ref_num ucell_x ucell_y ucell_z
        xf = float(fields[3])
        yf = float(fields[4])
        zf = float(fields[5])
        properties = [element, xf, yf, zf]

    elif style == 'magnetic':
        # id element xf yf zf ref_num ucell_x ucell_y ucell_z M: spin
        xf = float(fields[2])
        yf = float(fields[3])
        zf = float(fields[4])
        spin = float(fields[10].strip("M:"))
        properties = [element, xf, yf, zf, spin]
    else:
        raise Exception("Unsupported style for parsing rmc6f file format.")

    return atom_id, properties


def _read_process_rmc6f_lines_to_pos_and_cell(lines):
    """
    Processes the lines of rmc6f file to atom position dictionary and cell

    Parameters
    ----------
    lines: list[str]
        List of lines from rmc6f file.

    Returns
    ------
    pos : dict{int:list[str|float]}
        Dict for each atom id and Atoms properties based on rmc6f style.
        Basically, have 1) element and fractional coordinates for 'labels'
        or 'no_labels' style and 2) same for 'magnetic' style except adds
        the spin.
        Examples for 1) 'labels' or 'no_labels' styles or 2) 'magnetic' style:
            1) pos[aid] = [element, xf, yf, zf]
            2) pos[aid] = [element, xf, yf, zf, spin]
    cell: Cell object
        The ASE Cell object created from cell parameters read from the 'Cell'
        section of rmc6f file.
    """

    # Inititalize output pos dictionary
    pos = {}

    # Defined the header an section lines we process
    header_lines = [
        "Number of atoms:",
        "Supercell dimensions:",
        "Cell (Ang/deg):",
        "Lattice vectors (Ang):"]
    sections = ["Atoms"]

    # Construct header and sections regex
    header_lines_re = _read_construct_regex(header_lines)
    sections_re = _read_construct_regex(sections)

    section = None
    header = True

    # Process each line of rmc6f file
    pos = {}
    for line in lines:

        # check if in a section
        m = re.match(sections_re, line)
        if m is not None:
            section = m.group(0).rstrip().lstrip()
            header = False
            continue

        # header section
        if header:
            field = None
            val = None

            m = re.match(header_lines_re + r'\s+(.*)', line)
            if m is not None:
                field = m.group(1).lstrip().rstrip()
                val = m.group(2).lstrip().rstrip()

            if field is not None and val is not None:

                if field == "Number of atoms:":
                    pass
                    """
                    NOTE: Can just capture via number of atoms ingested.
                          Maybe use in future for a check.
                    code: natoms = int(val)
                    """

                if field.startswith('Supercell'):
                    pass
                    """
                    NOTE: wrapping back down to unit cell is not
                          necessarily needed for ASE object.

                    code: supercell = [int(x) for x in val.split()]
                    """

                if field.startswith('Cell'):
                    cellpar = [float(x) for x in val.split()]
                    cell = cellpar_to_cell(cellpar)

                if field.startswith('Lattice'):
                    pass
                    """
                    NOTE: Have questions about RMC fractionalization matrix for
                          conversion in data2config vs. the ASE matrix.
                          Currently, just support the Cell section.
                    """

        # main body section
        if section is not None:
            if section == 'Atoms':
                atom_id, atom_props = _read_line_of_atoms_section(line.split())
                pos[atom_id] = atom_props

    return pos, cell


def _write_output_column_format(columns, arrays):
    """
    Helper function to build output for data columns in rmc6f format

    Parameters
    ----------
    columns: list[str]
        List of keys in arrays. Will be columns in the output file.
    arrays: dict{str:np.array}
        Dict with arrays for each column of rmc6f file that are
        property of Atoms object.

    Returns
    ------
    property_ncols : list[int]
        Number of columns for each property.
    dtype_obj: np.dtype
        Data type object for the columns.
    formats_as_str: str
        The format for printing the columns.

    """
    fmt_map = {'d': ('R', '%14.6f '),
               'f': ('R', '%14.6f '),
               'i': ('I', '%8d '),
               'O': ('S', '%s'),
               'S': ('S', '%s'),
               'U': ('S', '%s'),
               'b': ('L', ' %.1s ')}

    property_types = []
    property_ncols = []
    dtypes = []
    formats = []

    # Take each column and setup formatting vectors
    for column in columns:
        array = arrays[column]
        dtype = array.dtype

        property_type, fmt = fmt_map[dtype.kind]
        property_types.append(property_type)

        # Flags for 1d vectors
        is_1d = len(array.shape) == 1
        is_1d_as_2d = len(array.shape) == 2 and array.shape[1] == 1

        # Construct the list of key pairs of column with dtype
        if (is_1d or is_1d_as_2d):
            ncol = 1
            dtypes.append((column, dtype))
        else:
            ncol = array.shape[1]
            for c in range(ncol):
                dtypes.append((column + str(c), dtype))

        # Add format and number of columns for this property to output array
        formats.extend([fmt] * ncol)
        property_ncols.append(ncol)

    # Prepare outputs to correct data structure
    dtype_obj = np.dtype(dtypes)
    formats_as_str = ''.join(formats) + '\n'

    return property_ncols, dtype_obj, formats_as_str


def _write_output(fileobj, header_lines, data, fmt, order=None):
    """
    Helper function to write information to the fileobj

    Parameters
    ----------
    fileobj : file|str
        A file like object or filename
    header_lines : list[str]
        Header section of output rmc6f file
    data: np.array[len(atoms)]
        Array for the Atoms section to write to file. Has
        the columns that need to be written on each row
    fmt: str
        The format string to use for writing each column in
        the rows of data.
    order : list[str]
        If not None, gives a list of atom types for the order
        to write out each.
    """
    # Write header section
    for line in header_lines:
        fileobj.write("%s \n" % line)

    # If specifying the order, fix the atom id and write to file
    natoms = data.shape[0]
    if order is not None:
        new_id = 0
        for atype in order:
            for i in range(natoms):
                if atype == data[i][1]:
                    new_id += 1
                    data[i][0] = new_id
                    fileobj.write(fmt % tuple(data[i]))
    # ...just write rows to file
    else:
        for i in range(natoms):
            fileobj.write(fmt % tuple(data[i]))


def _write_rmc_get_cell_from_cellpar(cellpar):
    """
    Convert RMCProfile cell paramters to ASE cell.

    Parameters
    ----------
    cellpar: list[float]
        Cell parameters (ie [a, b, c, alpha, beta, gamma]) to
        use in constructing the cell.

    Returns
    ------
    cell: Cell object
        The ASE Cell object created from the input cell parameters.
    """
    a, b, c, alpha, beta, gamma = cellpar

    # Handle orthorhombic cells separately to avoid rounding errors
    eps = 2 * np.spacing(90.0, dtype=np.float64)  # around 1.4e-14
    # alpha
    if abs(abs(alpha) - 90) < eps:
        cos_alpha = 0.0
        sin_alpha = 1.0
    else:
        cos_alpha = np.cos(alpha * np.pi / 180.0)
        sin_alpha = np.sin(alpha * np.pi / 180.0)
    # beta
    if abs(abs(beta) - 90) < eps:
        cos_beta = 0.0
    else:
        cos_beta = np.cos(beta * np.pi / 180.0)
    # gamma
    if abs(gamma - 90) < eps:
        cos_gamma = 0.0
    elif abs(gamma + 90) < eps:
        cos_gamma = 0.0
    else:
        cos_gamma = np.cos(gamma * np.pi / 180.0)

    # Get angles
    convert = np.pi / 180.
    alpha, beta, gamma = convert * np.array([alpha, beta, gamma])

    # Calculate volume using cell paramters
    s = 0.5 * (alpha + beta + gamma)
    sine_alpha = np.sin(s - alpha)
    sine_beta = np.sin(s - beta)
    sine_gamma = np.sin(s - gamma)
    sine_prod = np.sin(s) * sine_alpha * sine_beta * sine_gamma
    volume = 2. * a * b * c * np.sqrt(sine_prod)

    # Use calculated volume and cell paramters to get cell vectors
    va_0 = volume / (b * c * sin_alpha)
    va_1 = a * cos_gamma
    va_2 = a * cos_beta
    va = np.array([va_0, va_1, va_2])
    vb = b * np.array([0, sin_alpha, cos_alpha])
    vc = c * np.array([0, 0, 1])

    # Get returned cell using cell vectors
    cell = np.vstack([va, vb, vc])

    return cell


def read_rmc6f(fileobj, atom_type_map=None):
    """
    Parse a RMCProfile rmc6f file into ASE Atoms object


    Parameters
    ----------
    fileobj : file|str
        A file like object or filename.
    atom_type_map: dict{str:str}
        Map of atom types for conversions. Mainly used if there is
        an atom type in the file that is not supported by ASE but
        want to map to a supported atom type instead.

        Example to map deuterium to hydrogen:
        atom_type_map = { 'D': 'H' }

    Returns
    ------
    structure : Atoms
        The Atoms object read in from the rmc6f file.
    """

    if isinstance(fileobj, basestring):
        f = open(fileobj)

    lines = f.readlines()

    # Process the rmc6f file to extract positions and cell
    pos, cell = _read_process_rmc6f_lines_to_pos_and_cell(lines)

    # create an atom type map if one does not exist from unique atomic symbols
    if atom_type_map is None:
        symbols = [atom[0] for atom in pos.values()]
        atom_type_map = {atype: atype for atype in symbols}

    # Use map of tmp symbol to actual symbol
    for atom in pos.values():
        atom[0] = atom_type_map[atom[0]]

    # create Atoms from read-in data
    symbols = []
    scaled_positions = []
    spin = None
    magmoms = []
    for atom in pos.values():
        if len(atom) == 4:
            element, x, y, z = atom
        else:
            element, x, y, z, spin = atom

        element = atom_type_map[element]
        symbols.append(element)
        scaled_positions.append([x, y, z])
        if spin is not None:
            magmoms.append(spin)

    atoms = Atoms(scaled_positions=scaled_positions,
                  symbols=symbols,
                  cell=cell,
                  magmoms=magmoms,
                  pbc=[True, True, True])

    return atoms


def write_rmc6f(fileobj, atoms, order=None, atom_type_map=None):
    """
    Write output in rmc6f format - RMCProfile v6 fractional coordinates

    Parameters
    ----------
    fileobj : file|str
        A file like object or filename.
    atoms: Atoms object
        The Atoms object to be written.

    order : list[str]
        If not None, gives a list of atom types for the order
        to write out each.
    atom_type_map: dict{str:str}
        Map of atom types for conversions. Mainly used if there is
        an atom type in the Atoms object that is a placeholder
        for a different atom type. This is used when the atom type
        is not supported by ASE but is in RMCProfile.

        Example to map hydrogen to deuterium:
        atom_type_map = { 'H': 'D' }
    """

    if isinstance(fileobj, basestring):
        fileobj = open(fileobj, 'w')

    # get atom types and how many of each
    atom_types = set(atoms.get_chemical_symbols())
    natom_types = []
    for atom_type in atom_types:
        formula_re = r'{}*(\d+)'.format(atom_type)
        m = re.search(formula_re, atoms.get_chemical_formula())
        if m is not None:
            natom = 1
            if m.group(1):
                natom = m.group(1)
            natom_types.append(natom)
        else:
            msg = "Failed to parse chemical formula: {0} for atom type: {1}"
            formula = atoms.get_chemical_formula()
            raise RuntimeError(msg.format(formula, atom_type))

    # create an atom type map if one does not exist from unique atomic symbols
    if atom_type_map is None:
        symbols = list(set(np.array(atoms.get_chemical_symbols())))
        atom_type_map = {atype: atype for atype in symbols}

    # HEADER SECTION

    # get current date
    dt = datetime.datetime.now().date()
    y, m, d = (dt.year, dt.month, dt.day)
    date_format = "{day:02d}-{month:03d}-'{year:03d}"

    # get type and number of each atom type
    atom_types_list = [atom_type_map[atype] for atype in atom_types]
    atom_types_present = ' '.join(atom_types_list)
    natom_types_present = ' '.join(natom_types)

    header_lines = [
        "(Version 6f format configuration file)",
        "(Generated by ASE - Atomic Simulation Environment https://wiki.fysik.dtu.dk/ase/ )",  # noqa: E501
        "Metadata date:" + date_format.format(day=d, month=m, year=y),
        "Number of types of atoms:   {} ".format(len(atom_types)),
        "Atom types present:          {}".format(atom_types_present),
        "Number of each atom type:   {}".format(natom_types_present),
        "Number of moves generated:           0",
        "Number of moves tried:               0",
        "Number of moves accepted:            0",
        "Number of prior configuration saves: 0",
        "Number of atoms:                     {}".format(len(atoms)),
        "Supercell dimensions:                1 1 1"]

    # magnetic moments
    if atoms.has('magmoms'):
        spin_str = "Number of spins:                     {}"
        spin_line = spin_str.format(len(atoms.get_initial_magnetic_moments()))
        header_lines.extend([spin_line])

    density_str = "Number density (Ang^-3):              {}"
    density_line = density_str.format(len(atoms) / atoms.get_volume())
    cell_angles = [str(x) for x in atoms.get_cell_lengths_and_angles()]
    cell_line = "Cell (Ang/deg): " + ' '.join(cell_angles)
    header_lines.extend([density_line, cell_line])

    # get lattice vectors from cell lengths and angles
    # NOTE: RMCProfile uses a different convention for the fractionalization
    # matrix

    cell_parameters = atoms.get_cell_lengths_and_angles()
    cell = _write_rmc_get_cell_from_cellpar(cell_parameters)
    x_line = ' '.join(['{:12.6f}'.format(i) for i in cell[:][0]])
    y_line = ' '.join(['{:12.6f}'.format(i) for i in cell[:][1]])
    z_line = ' '.join(['{:12.6f}'.format(i) for i in cell[:][2]])
    lat_lines = ["Lattice vectors (Ang):", x_line, y_line, z_line]
    header_lines.extend(lat_lines)
    header_lines.extend(['Atoms:'])

    # ATOMS SECTION

    # create columns of data for atoms (fr_cols)
    fr_cols = ['id', 'symbols', 'scaled_positions', 'ref_num', 'ref_cell']
    if atoms.has('magmoms'):
        fr_cols.extend('magmom')

    # Collect data to be written out
    natoms = len(atoms)

    arrays = {}
    arrays['id'] = np.array(range(1, natoms + 1, 1), int)
    arrays['symbols'] = np.array(atoms.get_chemical_symbols())
    arrays['ref_num'] = np.zeros(natoms, int)
    arrays['ref_cell'] = np.zeros((natoms, 3), int)
    arrays['scaled_positions'] = np.array(atoms.get_scaled_positions(), float)

    # get formatting for writing output based on atom arrays
    ncols, dtype_obj, fmt = _write_output_column_format(fr_cols, arrays)

    # Pack fr_cols into record array
    data = np.zeros(natoms, dtype_obj)
    for column, ncol in zip(fr_cols, ncols):
        value = arrays[column]
        if ncol == 1:
            data[column] = np.squeeze(value)
        else:
            for c in range(ncol):
                data[column + str(c)] = value[:, c]

    # Use map of tmp symbol to actual symbol
    for i in range(natoms):
        data[i][1] = atom_type_map[data[i][1]]

    # Write the output
    _write_output(fileobj, header_lines, data, fmt, order=order)
