"""Some useful methods to clean main.py"""

from pathlib import Path


def get_list_of_reports(directory: str):
    """Function to return list (str) of pdf files in given path

    Returns:
        (str) list: list of strings with pdf files paths
    """
    pdf_files = []
    for path in directory.glob("**/*.[Pp][Dd][Ff]"):
        pdf_files.append(path)
    return pdf_files
    #return list(Path(path).glob('*.[Pp][Dd][Ff]'))
    
def get_unique_list(list):
    """Function to get list and return only unique elements from that list

    Returns:
        (str) list: list with unique elements
    """
    unique_list = []
    for element in list:
        if element not in unique_list:
            unique_list.append(element)
            
    return unique_list

def list_from_n_element_list(list, index):
    """Simple function to create list from provided index elements of list of lists

    Args:
        (list) list: list of lists
        (int) index: index of elements from list of lists

    Returns:
        (str/float) list: list comprehension of index elements from list of lists
    """
    
    return [item[index] for item in list]
