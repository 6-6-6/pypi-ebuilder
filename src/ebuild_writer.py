from pathlib import Path
from logging import debug, info, warn, error
import datetime

from .metadata_repr import PkgMetadata, ToBeGeneratedEbuilds
from .pypi_parser import PYPIParser


## TODO: use a config file
constant_info = {
    "cur_year": datetime.datetime.now().year,
    "cur_EAPI": 8,
    "maintainer_email": "example@example.com",
    "maintainer_name": "Adam",
    }


EBUILD_TEMPLATE = """# Copyright {cur_year} Gentoo Authors
# Distributed under the terms of the GNU General Public License v2
 
EAPI={cur_EAPI}
 
DESCRIPTION="{short_desc}"
HOMEPAGE="{homepage}"
SRC_URI="$(pypi_sdist_url "${{PN^}}" "${{PV}}")"

LICENSE="{lic_string}"
SLOT="0"
# some random keywords...
KEYWORDS="~amd64 ~arm64"
IUSE=""
 
DEPEND="{dep_string}"
RDEPEND="${{DEPEND}}"
BDEPEND=""

distutils_enable_tests pytest
"""

METADATA_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE pkgmetadata SYSTEM "http://www.gentoo.org/dtd/metadata.dtd">
<pkgmetadata>
    <maintainer type="person">
        <email>{maintainer_email}</email>
        <name>{maintainer_name}</name>
    </maintainer>
    <longdescription lang="en">
        {long_desc}
    </longdescription>
    <upstream>
        <remote-id type="pypi">{pypi_id}</remote-id>
    </upstream>
</pkgmetadata>
"""


def generate_metadata_if_not_existing(metadata_path, supp_informations: dict):
    """
    Write Portage -
    write metadata to provided path

    Input:
        metadata_path: pathlib.Path, the path of the metadata
        pypi_id: ToString, PyPI project name

    return: the number of characters written
    """
    informations = constant_info | supp_informations
    if not metadata_path.exists():
        metadata = METADATA_TEMPLATE.format(**informations)
        return open(metadata_path, 'w').write(metadata)
    else:
        return 0

def generate(repo_dir: Path,
             pypi_id, my_metadata: PkgMetadata):
    """
    Write Portage -
    resolve and (may recursively) generate the ebuild of a PyPI project

    Input:
        package: ToString, project name

    return: None
    """
    # dir of the project
    parent_dir = repo_dir / my_metadata.portage_cate / my_metadata.portage_name
    # ${P}
    ebuild_path = parent_dir / f"{my_metadata.portage_name}-{my_metadata.portage_version}.ebuild"
    info('Writing ebuild to', ebuild_path)
    parent_dir.mkdir(parents=True, exist_ok=True)
    # write ebuild
    with ebuild_path.open('w') as f:
        informations = my_metadata.export_dict() | constant_info
        content = EBUILD_TEMPLATE.format(**informations)
        f.write(content)

    # generate metadata, if it is not existing
    generate_metadata_if_not_existing(parent_dir / "metadata.xml", informations)

    # update existing_packages anyway
    ## will it cause infinity-loop?
    #self.existing_packages[package] = [category, package]

"""
# simply try-except, although it is expensive
if package in self.missing_packages:
    print(f"self.missing_packages.remove({package})")
    self.missing_packages.remove(package)

# recursively generate ebuild
if self.recursive:
    print("exexex", self.missing_packages)
    # copy to avoid "RuntimeError: Set changed size during iteration"
    for pkg in self.missing_packages.copy():
        if pkg not in self.existing_packages:
            self.generate(pkg)
"""
