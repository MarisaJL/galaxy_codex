#!/usr/bin/env python
import argparse
import sys
import time
import traceback
import xml.etree.ElementTree as et
from functools import lru_cache
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import pandas as pd
import requests
import shared
from tool import Tool
from tools import Tools
import yaml
from github import Github
from github.ContentFile import ContentFile
from github.Repository import Repository
from owlready2 import get_ontology

# Config variables
BIOTOOLS_API_URL = "https://bio.tools"

USEGALAXY_SERVER_URLS = {
    "UseGalaxy.org (Main)": "https://usegalaxy.org",
    "UseGalaxy.org.au": "https://usegalaxy.org.au",
    "UseGalaxy.eu": "https://usegalaxy.eu",
    "UseGalaxy.fr": "https://usegalaxy.fr",
}

DATA_PATH = Path(__file__).resolve().parent.parent.joinpath("data")
STAT_DATE = "2024.08.31"

@lru_cache  # need to run this for each suite, so just cache it
def get_all_installed_tool_ids_on_server(galaxy_url: str) -> List[str]:
    """
    Get all tool ids from a Galaxy server

    :param galaxy_url: URL of Galaxy instance
    """
    galaxy_url = galaxy_url.rstrip("/")
    base_url = f"{galaxy_url}/api"

    try:
        r = requests.get(f"{base_url}/tools", params={"in_panel": False})
        r.raise_for_status()
        tool_dict_list = r.json()
        tools = [tool_dict["id"] for tool_dict in tool_dict_list]
        return tools
    except Exception as ex:
        print(f"Server query failed with: \n {ex}")
        print(f"Could not query tools on server {galaxy_url}, all tools from this server will be set to 0!")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract Galaxy tools from GitHub repositories together with biotools and conda metadata"
    )
    subparser = parser.add_subparsers(dest="command")
    # Extract tools
    extract = subparser.add_parser("extract", help="Extract tools")
    extract.add_argument("--api", "-a", required=True, help="GitHub access token")
    extract.add_argument("--all", "-o", required=True, help="Filepath to JSON with all extracted tools")
    extract.add_argument("--all-tsv", "-j", required=True, help="Filepath to TSV with all extracted tools")
    extract.add_argument(
        "--planemo-repository-list",
        "-pr",
        required=False,
        help="Repository list to use from the planemo-monitor repository",
    )
    extract.add_argument(
        "--avoid-extra-repositories",
        "-e",
        action="store_true",
        default=False,
        required=False,
        help="Do not parse extra repositories in conf file",
    )
    extract.add_argument(
        "--test",
        "-t",
        action="store_true",
        default=False,
        required=False,
        help="Run a small test case using only the repository: https://github.com/TGAC/earlham-galaxytools",
    )

    # Filter tools based on ToolShed categories
    filtertools = subparser.add_parser("filter", help="Filter tools based on ToolShed categories")
    filtertools.add_argument(
        "--all",
        "-a",
        required=True,
        help="Filepath to JSON with all extracted tools, generated by extractools command",
    )
    filtertools.add_argument(
        "--categories",
        "-c",
        help="Path to a file with ToolShed category to keep in the extraction (one per line)",
    )
    filtertools.add_argument(
        "--filtered",
        "-f",
        required=True,
        help="Filepath to JSON with tools filtered based on ToolShed category",
    )
    filtertools.add_argument(
        "--tsv-filtered",
        "-t",
        required=True,
        help="Filepath to TSV with tools filtered based on ToolShed category",
    )
    filtertools.add_argument(
        "--status",
        "-s",
        help="Path to a TSV file with tool status - at least 3 columns: IDs of tool suites, Boolean with True to keep and False to exclude, Boolean with True if deprecated and False if not",
    )

    # Curate tools categories
    curatetools = subparser.add_parser("curate", help="Curate tools based on community review")
    curatetools.add_argument(
        "--filtered",
        "-f",
        required=True,
        help="Filepath to JSON with tools filtered based on ToolShed category",
    )
    curatetools.add_argument(
        "--curated",
        "-c",
        required=True,
        help="Filepath to TSV with curated tools",
    )
    curatetools.add_argument(
        "--wo-biotools",
        required=True,
        help="Filepath to TSV with tools not linked to bio.tools",
    )
    curatetools.add_argument(
        "--w-biotools",
        required=True,
        help="Filepath to TSV with tools linked to bio.tools",
    )
    curatetools.add_argument(
        "--status",
        "-s",
        help="Path to a TSV file with tool status - at least 3 columns: IDs of tool suites, Boolean with True to keep and False to exclude, Boolean with True if deprecated and False if not",
    )
    args = parser.parse_args()

    if args.command == "extract":
        tools = Tools(test=args.test)
        tools.init_by_searching(
            github_api=args.api,
            repository_list=args.planemo_repository_list,
            avoid_extra_repositories=args.avoid_extra_repositories,
        )
        shared.export_to_json(tools.export_tools_to_dict(), args.all)
        tools.export_tools_to_tsv(args.all_tsv, format_list_col=True)

    elif args.command == "filter":
        tools = Tools()
        tools.init_by_importing(tools=shared.load_json(args.all))
        # get categories and tools to exclude
        categories = shared.read_file(args.categories)
        # get status if file provided
        if args.status:
            status = pd.read_csv(args.status, sep="\t", index_col=0).to_dict("index")
        else:
            status = {}
        # filter tool lists
        tools.filter_tools(categories, status)
        if tools.tools:
            shared.export_to_json(tools.export_tools_to_dict(), args.filtered)
            tools.export_tools_to_tsv(
                args.tsv_filtered,
                format_list_col=True,
                to_keep_columns=["Suite ID", "Description", "To keep", "Deprecated"],
            )
        else:
            # if there are no ts filtered tools
            print(f"No tools found for category {args.filtered}")

    elif args.command == "curate":
        tools = Tools()
        tools.init_by_importing(tools=shared.load_json(args.all))
        try:
            status = pd.read_csv(args.status, sep="\t", index_col=0).to_dict("index")
        except Exception as ex:
            print(f"Failed to load tool_status.tsv file with:\n{ex}")
            print("Not assigning tool status for this community !")
            status = {}

        tools_wo_biotools, tools_with_biotools = tools.curate_tools(status)
        if tools.tools:
            tools.export_tools_to_tsv(
                args.curated,
                format_list_col=True,
            )
            tools_wo_biotools.export_tools_to_tsv(
                args.wo_biotools,
                format_list_col=True,
                to_keep_columns=["Suite ID", "Homepage", "Suite source"],
            )
            tools_with_biotools.export_tools_to_tsv(
                args.w_biotools,
                format_list_col=True,
                to_keep_columns=["Suite ID", "bio.tool name", "EDAM operations", "EDAM topics"],
            )
        else:
            # if there are no ts filtered tools
            print("No tools left after curation")
