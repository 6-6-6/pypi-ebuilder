import re
import glob
import portage
from logging import info, warn
from .pypi_parser import PYPIParser
from .metadata_repr import PkgMetadata

# TODO: this dependency can be replaced by `xml`
import xmltodict

p = portage.db[portage.root]["porttree"].dbapi

def upstream_has_pypi(metadata_dict):
    """
    Parse Portage -
    whether a package exists in PyPI

    Input:
        metadata_dict: dict, parsed metadata.xml

    return: PyPI project name or False
    """
    try:
        upstream = metadata_dict['pkgmetadata']['upstream']['remote-id']
    except:
        return False
    if isinstance(upstream, list):
        for u in upstream:
            if u['@type'] == 'pypi':
                return u['#text']
    else:
        if upstream['@type'] == 'pypi':
            return upstream['#text']
    return False

# reimplement find_package() by checking the metadata.xml of a pkg
def find_packages(repo):
    """
    Parse Portage -
    parse metadata of all pkgs from a Portage repository,
    add existing pkgs to self.existing_packages

    Input:
        repo: ToString, the location of a repository

    return: None
    """
    #len_old = len(self.existing_packages)
    cate_pkg_match = re.compile(f"{repo}/(.*)/(.+)/metadata.xml")

    pkg_cnt = 0
    for pkg_metadata in glob.glob(f'{repo}/**/metadata.xml', recursive=True):
        match = cate_pkg_match.match(pkg_metadata)
        if match:
            metadata_dict = xmltodict.parse(open(pkg_metadata).read())
            pypi_id = upstream_has_pypi(metadata_dict)
            if pypi_id:
                try:
                    pkg_highest_match = p.xmatch("match-all", (f"{match.group(1)}/{match.group(2)}"))[-1]
                    pkg_highest_ver = portage.catpkgsplit(pkg_highest_match)[-1]
                except:
                    warn(f"{match.group(1)}/{match.group(2)} not found")
                    pkg_highest_ver = '0'
                ## update the static member...
                PYPIParser.PN_database[pypi_id] = PkgMetadata(pypi_id,
                                                              match.group(1), match.group(2),
                                                              portage_version=pkg_highest_ver)
                pkg_cnt += 1

    info(f'Found {pkg_cnt} packages in {repo}')
