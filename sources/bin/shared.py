#!/usr/bin/env python

import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import pandas as pd
import requests
from github import Github
from github.ContentFile import ContentFile
from github.Repository import Repository
from requests.exceptions import ConnectionError


def get_first_commit_for_folder(tool: ContentFile, repo: Repository) -> str:
    """
    Get the date of the first commit in the tool folder

    :param commit_date: date of the first commit
    """

    # Get commits related to the specific folder
    commits = repo.get_commits(path=tool.path)

    # Get the last commit in the history (which is the first commit made to the folder)
    first_commit = commits.reversed[0]

    # Extract relevant information about the first commit
    commit_date = first_commit.commit.author.date.date()

    return str(commit_date)


def format_list_column(col: pd.Series) -> pd.Series:
    """
    Format a column that could be a list before exporting
    """
    return col.apply(lambda x: ", ".join(str(i) for i in x))


def read_file(filepath: Optional[str]) -> List[str]:
    """
    Read an optional file with 1 element per line

    :param filepath: path to a file
    """
    if filepath is None:
        return []
    fp = Path(filepath)
    if fp.is_file():
        with fp.open("r") as f:
            return [x.rstrip() for x in f.readlines()]
    else:
        return []


def export_to_json(data: List[Dict], output_fp: str, sort_keys: bool = True, default = list) -> None:
    """
    Export to a JSON file
    """
    with Path(output_fp).open("w") as f:
        json.dump(data, f, indent=4, sort_keys=sort_keys, default=default)


def load_json(input_df: str) -> Dict:
    """
    Read a JSON file
    """
    with Path(input_df).open("r") as t:
        content = json.load(t)
    return content


def read_suite_per_tool_id(tool_fp: str) -> Dict:
    """
    Read the tool suite table and extract a dictionary per tool id
    """
    tool_suites = load_json(tool_fp)
    tools = {}
    for suite in tool_suites:
        for tool in suite["Galaxy tool ids"]:
            tools[tool] = {
                "Galaxy wrapper id": suite["Galaxy wrapper id"],
                "Galaxy wrapper owner": suite["Galaxy wrapper id"],
                "EDAM operation": suite["EDAM operation"],
            }
    return tools


def get_request_json(url: str, headers: dict, retries: int = 3, delay: float = 2.0) -> dict:
    """
    Perform a GET request to retrieve JSON output from a specified URL, with retry on ConnectionError.

    :param url: URL to send the GET request to.
    :param headers: Headers to include in the GET request.
    :param retries: Number of retry attempts in case of a ConnectionError (default is 3).
    :param delay: Delay in seconds between retries (default is 2.0 seconds).
    :return: JSON response as a dictionary, or None if all retries fail.
    :raises ConnectionError: If all retry attempts fail due to a connection error.
    :raises SystemExit: For any other request-related errors.
    """
    attempt = 0  # Track the number of attempts

    while attempt < retries:
        try:
            r = requests.get(url, auth=None, headers=headers)
            r.raise_for_status()  # Raises an HTTPError for unsuccessful status codes
            return r.json()  # Return JSON response if successful
        except ConnectionError as e:
            attempt += 1
            if attempt == retries:
                raise ConnectionError(
                    "Connection aborted after multiple retries: Remote end closed connection without response"
                ) from e
            print(f"Connection error on attempt {attempt}/{retries}. Retrying in {delay} seconds...")
            time.sleep(delay)  # Wait before retrying
        except requests.exceptions.RequestException as e:
            # Handles all other exceptions from the requests library
            raise SystemExit(f"Request failed: {e}")
        except ValueError as e:
            # Handles cases where the response isn't valid JSON
            raise ValueError("Response content is not valid JSON") from e

    # Return None if all retries are exhausted and no response is received
    return {}


def format_date(date: str) -> str:
    return datetime.fromisoformat(date).strftime("%Y-%m-%d")


def shorten_tool_id(tool: str) -> str:
    """
    Shorten tool id
    """
    if "toolshed" in tool:
        return tool.split("/")[-2]
    else:
        return tool


def get_edam_operation_from_tools(selected_tools: list, all_tools: dict) -> List:
    """
    Get list of EDAM operations of the tools

    :param selected_tools: list of tool suite ids
    :param all_tools: dictionary with information about all tools
    """
    edam_operation = set()
    for t in selected_tools:
        if t in all_tools:
            edam_operation.update(set(all_tools[t]["EDAM operation"]))
        else:
            print(f"{t} not found in all tools")
    return list(edam_operation)


def reduce_ontology_terms(terms: List, ontology: Any) -> List:
    """
    Reduces a list of Ontology terms, to include only terms that are not super-classes of one of the other terms.
    In other terms all classes that have a subclass in the terms are removed.

    :terms: list of terms from that ontology
    :ontology: Ontology
    """
    # if list is empty do nothing
    if not terms:
        return terms

    classes = [ontology.search_one(label=term) for term in terms]
    check_classes = [cla for cla in classes if cla is not None]  # Remove None values

    new_classes = []
    for cla in check_classes:
        try:
            # get all subclasses
            subclasses = list(cla.subclasses())

            # check if any of the other classes is a subclass
            include_class = True
            for subcla in subclasses:
                for cla2 in check_classes:
                    if subcla == cla2:
                        include_class = False

            # only keep the class if it is not a parent class
            if include_class:
                new_classes.append(cla)

        except Exception as e:
            print(f"Error processing class {cla}: {e}")

    # convert back to terms, skipping None values
    new_terms = [cla.label[0] for cla in new_classes if cla is not None]
    # print(f"Terms: {len(terms)}, New terms: {len(new_terms)}")
    return new_terms


def get_string_content(cf: ContentFile) -> str:
    """
    Get string of the content from a ContentFile

    :param cf: GitHub ContentFile object
    """
    return base64.b64decode(cf.content).decode("utf-8")


def get_github_repo(url: str, g: Github) -> Repository:
    """
    Get a GitHub Repository object from an URL

    :param url: URL to a GitHub repository
    :param g: GitHub instance
    """
    if not url.startswith("https://github.com/"):
        raise ValueError
    if url.endswith("/"):
        url = url[:-1]
    if url.endswith(".git"):
        url = url[:-4]
    u_split = url.split("/")
    return g.get_user(u_split[-2]).get_repo(u_split[-1])

def get_shed_attribute(attrib: str, shed_content: Dict[str, Any], empty_value: Any) -> Any:
    """
    Get a shed attribute

    :param attrib: attribute to extract
    :param shed_content: content of the .shed.yml
    :param empty_value: value to return if attribute not found
    """
    if attrib in shed_content:
        return shed_content[attrib]
    else:
        return empty_value

def get_last_url_position(toot_id: str) -> str:
    """
    Returns the second last url position of the toot_id, if the value is not a
    url it returns the toot_id. So works for local and toolshed
    installed tools.

    :param tool_id: galaxy tool id
    """

    if "/" in toot_id:
        toot_id = toot_id.split("/")[-1]
    return toot_id

