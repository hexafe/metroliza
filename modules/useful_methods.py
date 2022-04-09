import os

"""
Some useful methods to clean main.py
"""

def get_list_of_reports(path: str):
    """
    Function to return list (str) of pdf files in given direction path
    :param path: (str) path to check for pdf files
    :return: list (str) of dir including file name
    """
    list_of_reports = []
    with os.scandir(path) as it:
        for entry in it:
            if (entry.name.endswith(".PDF") or entry.name.endswith(".pdf")) and entry.is_file():
                list_of_reports.append(entry.path)
    return list_of_reports


def get_unique_list(list):
    """
    Function to get list and return only unique elements from that list
    :param list: input list
    :return: list with only unique elements from input list
    """
    unique_list = []
    for element in list:
        if element not in unique_list:
            unique_list.append(element)
    return unique_list