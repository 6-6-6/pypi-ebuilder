from logging import debug, info, warn, error
import argparse
import sys
import json
import os
from typing import List
import requests
import re
import glob
from collections import defaultdict
from pathlib import Path

from .metadata_repr import PkgMetadata, ToBeGeneratedEbuilds

"""
I am going to represent everything in a intermedia format (on the basis of portage)

This file serves as a translator which converts pypi metadata to a intermedia format.
"""


___supported_python_versions = ['3.10', '3.11', '3.12']

class PYPIParser():
    # some pypi => portage mappings
    PN_exceptions = {
        'bs4': PkgMetadata('bs4',
                           'dev-python', 'beautifulsoup'),
        'funcsigs': PkgMetadata('funcsigs',
                           'dev-lang', 'python'),
        'opencv-python': PkgMetadata('opencv-python',
                                     'media-libs', 'opencv'),# ,'python'),
        'tensorflow': PkgMetadata('tensorflow',
                                  'sci-libs', 'tensorflow'),
        'tensorflow-cpu': PkgMetadata('tensorflow-cpu',
                                      'sci-libs', 'tensorflow'),
        'tensorflow-gpu': PkgMetadata('tensorflow-gpu',
                                      'sci-libs', 'tensorflow', 'gpu'),
        'torch' : PkgMetadata('torch',
                              'sci-libs', 'pytorch'),
    }

    # license mapping
    license_mapping = {
        'BSD 3-clause': 'BSD',
        'BSD 3-clause License': 'BSD',
        'BSD 3-Clause License': 'BSD',
    }

    #
    use_special = {
        "dev": "ignore"
    }

    # dep patterns
    dep_use = re.compile("(.+); extra == '(.+)'")
    dep_python_ver = re.compile('(.+); python_version < "(.+)"')
    dep_fallback = re.compile("(.+); (.+)")
    ## dep's PV patterns
    # handle: package ([<>]=version)
    depv_normal = re.compile(r"(^[ \(]+) *\(?([<>]=?) *([0-9\.\-]+)\)?")
    # handle: package ([~=]=version)
    depv_locked = re.compile(r"(^[ \(]+) *?\(?([~=])= *([0-9\.\-]+)\)?")
    # handle: package (!=version)
    depv_rej = re.compile(r"(^[ \(]+) *\(?!= *([0-9\.\-]+)\)?")

    # database got by parsing the host's portage repo
    ## static member, meant to be modified by portage_parser
    PN_database = {}
    '''
    translate pypi staffs to portage
    '''
    @staticmethod
    def catepn(pypi_id):
        """
        regularize PyPI project names

        Input:
            package: String, PyPI project name

        Return: String: somehow regularized name
        """
        if pypi_id in PYPIParser.PN_exceptions:
            return PYPIParser.PN_exceptions[pypi_id].portage_cate, \
                   PYPIParser.PN_exceptions[pypi_id].portage_name, \
                   True
        elif pypi_id in PYPIParser.PN_database:
            return PYPIParser.PN_database[pypi_id].portage_cate, \
                   PYPIParser.PN_database[pypi_id].portage_name, \
                   True
        else:
            return "dev-python", \
                   pypi_id.lower().replace('.', '-').replace('_', '-'), \
                   False

    @staticmethod
    def pv(pypi_pv):
        return pypi_pv
    
    @staticmethod
    def license(pypi_lic) -> str:
        if pypi_lic in PYPIParser.license_mapping:
            return PYPIParser.license_mapping[pypi_lic]
        else:
            return pypi_lic

    @staticmethod
    def get_iuse_and_depend(project_json) -> dict[str, List[str]]:
        """
        Parse PyPI -
        resolve USE flag and DEPEND of a project

        Input:
            project: dict, the json metadata provided by PyPI

        return: dict of {use: deps}
                where _default is the key for the necessities
                where deps may contain some version constraints
        """
        requires = project_json['info']['requires_dist']
        deps = defaultdict(list)
#        simple = []
#        uses = defaultdict(list)
        if requires == None:
            return deps
        for req in requires:
            ## TODO: update it so we can do less res
            match_use = PYPIParser.dep_use.match(req)
            match_pyver = PYPIParser.dep_python_ver.match(req)
            match_fallback = PYPIParser.dep_fallback.match(req)
            ##
            if match_use:
                dep_pypi_id = match_use.group(1).strip()
                use = match_use.group(2)
                if PYPIParser.use_special.get(use) == "ignore":
                    continue
                else:
                    _pypi_id, _pv = PYPIParser.parse_single_dep(dep_pypi_id)
                    deps[use].append((_pypi_id, _pv))
            elif match_pyver:
                dep_pypi_id = match_pyver.group(1).strip()
                if not dep_pypi_id.startswith('backports'):
                    # we don't need backports for python3
                    _pypi_id, _pv = PYPIParser.parse_single_dep(dep_pypi_id)
                    deps["_default"].append((_pypi_id, _pv))
            elif match_fallback:
                warn(f"Not implemented parser for dep-string: '{req}'")
            else:
                dep_pypi_id = req.strip()
                _pypi_id, _pv = PYPIParser.parse_single_dep(dep_pypi_id)
                deps["_default"].append((_pypi_id, _pv))

        return deps
    
    @staticmethod
    def parse_single_dep(dep_string):
        # ignore strings after ';'
        if len(dep_string.split(';')) > 1:
            warn(f"ignoring the latter part of a conditional dep string {dep_string}")
        dep_string = dep_string.split(';')[0].strip()
        # ignore strings after '[', e.g. horovod[torch]
        if len(dep_string.split('[')) > 1:
            warn(f"ignoring the latter part of a conditional dep string {dep_string}")
        dep_string = dep_string.split('[')[0]

        # handle: package ([<>]=version)
        match_normal = PYPIParser.depv_normal.match(dep_string)
        # handle: package ([~=]=version)
        match_locked = PYPIParser.depv_locked.match(dep_string)
        # handle: package (!=version)
        match_rej = PYPIParser.depv_rej.match(dep_string)

        if match_normal:
            pypi_id = match_normal.group(1)
            specifier = match_normal.group(2)
            version = match_normal.group(3)
        #    return '{}{}-{}[${{PYTHON_USEDEP}}]'.format(specifier, self.get_package_name(name), version)
        elif match_locked:
            pypi_id = match_locked.group(1)
            specifier = match_locked.group(2)
            version = match_locked.group(3)
#            return '{}{}-{}[${{PYTHON_USEDEP}}]'.format(specifier, self.get_package_name(name), version)
        elif match_rej:
            pypi_id = match_rej.group(1)
            specifier = "!="
            version = match_rej.group(2)
#            return '!={}-{}[${{PYTHON_USEDEP}}]'.format(self.get_package_name(name), version)
        elif " " not in dep_string:
            pypi_id = dep_string
            specifier = None
            version = None
        else:
            error(f"not handled dep string {dep_string}")
            #raise ValueError
            pypi_id = dep_string.split(" ")[0]
            specifier = None
            version = None
        print(pypi_id, (specifier, version))
        return pypi_id, (specifier, version)

def get_project_python_versions(self, project):
    """
    Parse PyPI -
    resolve PYTHON_COMPAT of a project

    Input:
        project: dict, the json metadata provided by PyPI

    return: list of String, supported Python versions
    """
    classifiers = project['info']['classifiers']
    res = []
    for classifier in classifiers:
        for version in ___supported_python_versions:
            if classifier == 'Programming Language :: Python :: {}'.format(version):
                res.append(version)
                break

    # some packages just specified Python3
    if len(res) == 0:
        res = ___supported_python_versions
    return res



class PYPICommunicator():

    upstream_template = "https://pypi.org/pypi/{}/json"

    def test(self, package):
        warn(f"Retriving metadata of {package}, uri: {self.upstream_template.format(package)}")
        resp = requests.get(self.upstream_template.format(package))
        body = json.loads(resp.content)
        ###############################
        #
        try:
            pypi_id = body["info"]["name"]
        except Exception as e:
            print(body)
            error(f"encountering {e} for pkg: '{package}'")
            raise ValueError
        #
        portage_cate, portage_name, existed = PYPIParser.catepn(pypi_id)
        portage_version = PYPIParser.pv(body['info']['version'])
        portage_lic = PYPIParser.license(body['info']['license'])
        #
        deps = PYPIParser.get_iuse_and_depend(body)
        #
        homepage = body['info']['home_page']
        short_desc = body['info']['summary']
        long_desc = body['info']['description']
        ###############################
        if not existed:
            with ToBeGeneratedEbuilds.lock:
                pkgmeta = PkgMetadata(pypi_id,
                            portage_cate, portage_name,
                            portage_version, portage_lic)
                pkgmeta.add_descriptions(short_desc, long_desc)
                pkgmeta.add_homepage(homepage)
                pkgmeta.parse_deps(deps)
                ToBeGeneratedEbuilds.payload[pypi_id] = pkgmeta
        #
        print(portage_cate, portage_name)
        print(portage_version)
        print(portage_lic)
        return
        #
        versions = self.get_project_python_versions(body)
        compat = ' '.join(['python' + version.replace('.','_') for version in versions])
        #
        iuse_and_depend = self.get_iuse_and_depend(body)
        # verbose logging
        debug('Python versions', versions)
        debug('Homepage', body['info']['home_page'])
        debug('Description', body['info']['summary'])
        debug('License', license)
        debug('Version', body['info']['version'])
        debug('IUSE and Depend', iuse_and_depend)
        # get category of the package
        category = self.existing_packages.get(package, [self.category])[0]
