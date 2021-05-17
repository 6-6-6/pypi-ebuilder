import argparse
import sys
import json
import os
import requests
import re
import glob
from collections import defaultdict
from pathlib import Path

# TODO: this dependency can be replaced by `xml`
import xmltodict

def regularize_package_name(package):
    """
    regularize PyPI project names

    Input:
        package: String, PyPI project name

    Return: String
    """
    return package.lower() \
                  .replace('.', '-')

class PyPIEbuilder():
    # metadata template
    metadata_template = '''<?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE pkgmetadata SYSTEM "http://www.gentoo.org/dtd/metadata.dtd">
    <pkgmetadata>
      <maintainer type="person">
        <email>someone@example.org</email>
        <name>Pypi ebuilder</name>
      </maintainer>
      <longdescription lang="en">
      there will be description later.
    </longdescription>
      <upstream>
        <remote-id type="pypi">{}</remote-id>
      </upstream>
    </pkgmetadata>
    '''

    # upstream template
    upstream_template = "https://pypi.org/pypi/{}/json"

    # PYTHON_COMPAT
    supported_python_versions = ['3.7', '3.8']

    # already provided by other gentoo packages
    # and thes pkgs either do not provide its pypi upstream in its metadata.xml
    #                   or has USE conditional codes
    #                   or has alternative names
    exceptions = {
        'bs4': 'dev-python/beautifulsoup:4',
        'funcsigs': '',
        'opencv-python': 'media-libs/opencv[python]',
        'tensorflow': 'sci-libs/tensorflow',
        'tensorflow-cpu': 'sci-libs/tensorflow',
        'tensorflow-gpu': 'sci-libs/tensorflow[gpu]',
        'torch' : 'sci-libs/pytorch',
    }

    # unneeded packages for python2 backports
    removals = [ 'backports.lzma' ]

    # license mapping
    license_mapping = {
        'BSD 3-clause': 'BSD',
        'BSD 3-clause License': 'BSD',
        'BSD 3-Clause License': 'BSD',
    }

    # useless dependencies
    use_blackhole = set(('dev',))

    def __init__(self, category, repo, repoman: bool, recursive: bool, verbose: bool, get_uri_from_pypi: bool):
        """
        Input:
            category: String, the default category of the generated ebuild files
            repo: Path / String, location of the overlay
            repoman: bool, generate manifest or not
            recursive: bool, recursively generate ebuild or not
            verbose: bool
            get_uri_from_pypi: bool
        """
        self.category = category

        # key: regularized PyPI project name
        # value: [Portage category, Portage package]
        self.existing_packages = dict()
        # contains: regularized PyPI project name
        self.missing_packages = set()
        # path to the repository where I will generate ebuild files
        self.repo = repo
        # run repoman or not
        self.repoman = repoman
        # recursively generate ebuild files or not
        self.recursive = recursive
        # verbose
        self.verbose = verbose
        # whether it should use the uri provided by pypi instead Gentoo's "mirror" syntax
        self.get_uri_from_pypi = get_uri_from_pypi

    def get_package_name(self, package):
        """
        Connect PyPI and Portage -
        get Portage package name by PyPI project name

        Input:
            package: String, PyPI project name

        return: String, ${PN}
        """
        # regularize it anyway
        package = regularize_package_name(package)
        # if it matches exceptions, it will return the matching item
        if package in PyPIEbuilder.exceptions:
            return PyPIEbuilder.exceptions[package]

        # if it exists in self.existing_pkgs, it will return the matching pkg
        # if not, then add the pkg to self.missing_pkgs
        if package in self.existing_packages:
            category, gentoo_package = self.existing_packages[package]
            return f'{category}/{gentoo_package}'
        # there are cases that pypi_id and requirements are inconsistent
        elif package.replace('-', '_') in self.existing_packages:
            category, gentoo_package = self.existing_packages[package.replace('-', '_')]
            return f'{category}/{gentoo_package}'
        elif package.replace('_', '-') in self.existing_packages:
            category, gentoo_package = self.existing_packages[package.replace('_', '-')]
            return f'{category}/{gentoo_package}'
        else:
            print("Package '%s' does not exist" % package)
            self.missing_packages.add(package)
            return f'{self.category}/{package}'


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
            for version in PyPIEbuilder.supported_python_versions:
                if classifier == 'Programming Language :: Python :: {}'.format(version):
                    res.append(version)
                    break

        # some packages just specified Python3
        if len(res) == 0:
            res = PyPIEbuilder.supported_python_versions
        return res

    def convert_dependency(self, depend):
        """
        Parse PyPI -
        dependency translator

        Input:
            depend: String, PyPI dependency

        return: String, Portage dependency
        """
        # ignore strings after ';'
        depend = depend.split(';')[0].strip()
        # ignore strings after '[', e.g. horovod[torch]
        depend = depend.split('[')[0]

        # handle: package ([<>]=version)
        match = re.match("(.+) \(?([<>]=?) *([0-9\.\-]+)\)?", depend)
        if match:
            name = match.group(1)
            specifier = match.group(2)
            version = match.group(3)
            return '{}{}-{}[${{PYTHON_USEDEP}}]'.format(specifier, self.get_package_name(name), version)

        # handle: package ([~=]=version)
        match = re.match("(.+) \(?([~=])= *([0-9\.\-]+)\)?", depend)
        if match:
            name = match.group(1)
            specifier = match.group(2)
            version = match.group(3)
            return '{}{}-{}[${{PYTHON_USEDEP}}]'.format(specifier, self.get_package_name(name), version)

        # handle: package (!=version)
        match = re.match("(.+) \(?!= *([0-9\.\-]+)\)?", depend)
        if match:
            name = match.group(1)
            version = match.group(2)
            return '!={}-{}[${{PYTHON_USEDEP}}]'.format(self.get_package_name(name), version)

        # strip all exotic (.*), e.g. (~=1-32-0), (~=3-7-4), (<2,>=1-21-1)
        #match = re.match("(.+) \([^()]*\)", depend)
        #if match:
        #    name = match.group(1)
        #    return '{}[${{PYTHON_USEDEP}}]'.format(self.get_package_name(name))

        return '{}[${{PYTHON_USEDEP}}]'.format(self.get_package_name(depend))

    def get_iuse_and_depend(self, project):
        """
        Parse PyPI -
        resolve USE flag and DEPEND of a project

        Input:
            project: dict, the json metadata provided by PyPI

        return: String, ebuild-style USE and DEPEND
        """
        requires = project['info']['requires_dist']
        simple = []
        uses = defaultdict(list)
        if requires == None:
            return ''
        for req in requires:
            for rm in PyPIEbuilder.removals:
                if rm in req:
                    break
            else:
                match = re.match("(.+); extra == '(.+)'", req)
                if match:
                    name = match.group(1).strip()
                    use = match.group(2)
                    if use in PyPIEbuilder.use_blackhole:
                        continue
                    uses[use].append(self.convert_dependency(name))
                else:
                    match = re.match('(.+); python_version < "(.+)"', req)
                    if match:
                        name = match.group(1).strip()
                        if not name.startswith('backports'):
                            # we don't need backports for python3
                            simple.append(self.convert_dependency(name))
                    else:
                        simple.append(self.convert_dependency(req.strip()))

        use_res = []
        for use in uses:
            use_res.append('{}? ( {} )'.format(use, '\n\t\t'.join(uses[use])))
        iuse = 'IUSE="{}"'.format(" ".join(uses.keys()))
        return iuse + '\n' + 'RDEPEND="' + '\n\t'.join(simple + use_res) + '"'



    def upstream_has_pypi(self, metadata_dict):
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
    def find_packages(self, repo):
        """
        Parse Portage -
        parse metadata of all pkgs from a Portage repository,
        add existing pkgs to self.existing_packages

        Input:
            repo: ToString, the location of a repository

        return: None
        """
        len_old = len(self.existing_packages)
        cate_pkg_match = re.compile(f"{repo}/(.*)/(.+)/metadata.xml")

        for pkg_metadata in glob.glob(f'{repo}/**/metadata.xml', recursive=True):
            match = cate_pkg_match.match(pkg_metadata)
            if match:
                pypi_id = self.upstream_has_pypi(xmltodict.parse(open(pkg_metadata).read()))
                if pypi_id:
                    self.existing_packages[regularize_package_name(pypi_id)] = [match.group(1), match.group(2)]

        print(f'Found {len(self.existing_packages) - len_old} packages in {repo}')

    # TODO: update maintainer
    # TODO: accept description
    def generate_metadata_if_not_exists(self, metadata_path, pypi_id):
        """
        Write Portage -
        write metadata to provided path

        Input:
            metadata_path: pathlib.Path, the path of the metadata
            pypi_id: ToString, PyPI project name

        return: the number of characters written
        """
        if not metadata_path.exists():
            metadata = PyPIEbuilder.metadata_template.format(pypi_id)
            return open(metadata_path, 'w').write(metadata)
        return 0

    def generate(self, package):
        """
        Write Portage -
        resolve and (may recursively) generate the ebuild of a PyPI project

        Input:
            package: ToString, project name

        return: None
        """
        print('Generating {} to {}'.format(package, self.repo))
        resp = requests.get(self.upstream_template.format(package))
        body = json.loads(resp.content)

        #
        pv = body['info']['version']
        #
        pypi_id = body['info']['name']
        package = regularize_package_name(pypi_id)
        versions = self.get_project_python_versions(body)
        compat = ' '.join(['python' + version.replace('.','_') for version in versions])
        #
        license = body['info']['license']
        if license in PyPIEbuilder.license_mapping:
            license = PyPIEbuilder.license_mapping[license]
        iuse_and_depend = self.get_iuse_and_depend(body)
        # verbose logging
        if self.verbose:
            print('Python versions', versions)
            print('Homepage', body['info']['home_page'])
            print('Description', body['info']['summary'])
            print('License', license)
            print('Version', body['info']['version'])
            print('IUSE and Depend', iuse_and_depend)

        # get category of the package
        category = self.existing_packages.get(package, [self.category])[0]

        # dir of the project
        dir = Path(self.repo) / category / package
        # ${P}
        path = dir / "{}-{}.ebuild".format(package, pv)
        print('Writing to', path)
        dir.mkdir(parents=True, exist_ok=True)
        # write ebuild
        with path.open('w') as f:
            content = '# Copyright 1999-2021 Gentoo Authors\n'
            content += '# Distributed under the terms of the GNU General Public License v2\n\n'
            content += 'EAPI=7\n\n'
            content += 'PYTHON_COMPAT=( {} )\n\n'.format(compat)
            content += 'inherit distutils-r1\n\n'
            content += 'DESCRIPTION="{}"\n'.format(body['info']['summary'])
            src_uri = 'SRC_URI="mirror://pypi/${PN:0:1}/${PN}/${P}.tar.gz"\n'
            if self.get_uri_from_pypi:
                #
                for release_body in body['releases'][pv]:
                    if release_body['python_version'] == 'source':
                        provided_srcuri = release_body['url']
                        src_uri += 'SRC_URI="{}"\n'.format(provided_srcuri)
                        break
            content += src_uri
            content += 'HOMEPAGE="{}"\n\n'.format(body['info']['home_page'])
            content += 'LICENSE="{}"\n'.format(body['info']['license'])
            content += 'SLOT="0"\n'
            content += 'KEYWORDS="~amd64"\n\n'
            content += iuse_and_depend
            content += '\ndistutils_enable_tests pytest\n'

            f.write(content)

        self.generate_metadata_if_not_exists(dir / "metadata.xml", pypi_id)

        if self.repoman:
            os.system('cd %s && repoman manifest' % (dir))

        # regularize_package_name() is called before
        # update existing_packages anyway
        self.existing_packages[package] = [category, package]
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--category', help='the default category', default='dev-python')
    parser.add_argument('--get-uri-from-pypi', action='store_true', help='whether it should use the uri provided by pypi instead Gentoo\'s "mirror" syntax.')
    parser.add_argument('-r', '--repos', action='append',
        help='existing Portage repositories, do not specify it if you want it to find all repositories automatically',
        default=[])
    parser.add_argument('-t', '--target', help='target repo directory', default='../gentoo-localrepo')
    parser.add_argument('-v', '--verbose', action='store_true', help='enable verbose logging')
    parser.add_argument('-R', '--recursive', action='store_true', help='generate ebuild recursively')
    parser.add_argument('-p', '--repoman', action='store_true', help='run "repoman manifest" after generation')
    parser.add_argument('packages', nargs='+')
    args = parser.parse_args()

    # setup repo structure
    metadata = Path(args.target) / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    with (metadata / "layout.conf").open('w') as f:
        f.write("masters = gentoo\nauto-sync = false\n")

    # instantiate PyPIEbuilder
    ebuilder = PyPIEbuilder(args.category, args.target, args.repoman, args.recursive, args.verbose, args.get_uri_from_pypi)

    # parse
    if len(args.repos) == 0:
        import portage
        # TODO: find out what to do if portage.db has multiple keys
        eroot = next(iter(portage.db.keys()))
        repo_names = portage.db[eroot]["vartree"].settings.repositories.prepos_order
        repos = []
        for name in repo_names:
            repos.append(portage.db[eroot]["vartree"].settings.repositories.treemap.get(name))
    else:
        repos = args.repos

    for repo in repos:
        ebuilder.find_packages(repo)

    # run
    for package in args.packages:
        ebuilder.generate(package)

if __name__ == "__main__":
    main()
