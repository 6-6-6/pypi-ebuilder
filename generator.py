import argparse
import sys
import json
import os
import requests
import re
import glob
from collections import defaultdict
from pathlib import Path

# TODO: set via CLI args
DEFAULT_CATEGORY = 'dev-python'

#
supported_python_versions = ['3.6', '3.7', '3.8']

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

existing_packages = dict()
missing_packages = set()

def regularize_package_name(package):
    return package.lower() \
                  .replace('.', '-')

def get_package_name(package, category):
    gentoo_package = regularize_package_name(package)
    if package in exceptions:
        return exceptions[package]

    try:
        category, gentoo_package = existing_packages[package]
    except:
        print("Package '%s' does not exist" % package)
        missing_packages.add(package)
    return f'{category}/{gentoo_package}'

def get_project_python_versions(project):
    classifiers = project['info']['classifiers']
    res = []
    for classifier in classifiers:
        for version in supported_python_versions:
            if classifier == 'Programming Language :: Python :: {}'.format(version):
                res.append(version)
                break
    
    # some packages just specified Python3
    if len(res) == 0:
        res = supported_python_versions
    return res

def convert_dependency(depend, default_category):
    # ignore strings after ';'
    depend = depend.split(';')[0].strip()
    # ignore strings after '[', e.g. horovod[torch]
    depend = depend.split('[')[0]
    # handle: package (>=version)
    match = re.match("(.+) \(>=(.+)\)", depend)
    if match:
        name = match.group(1)
        version = match.group(2)
        return '>={}-{}[${{PYTHON_USEDEP}}]'.format(get_package_name(name, default_category), version)
    else:
        # handle: package (==version)
        match = re.match("(.+) \(==(.+)\)", depend)
        if match:
            name = match.group(1)
            version = match.group(2)
            return '={}-{}[${{PYTHON_USEDEP}}]'.format(get_package_name(name, default_category), version)
        else:
            # strip all exotic (.*), e.g. (~=1-32-0), (~=3-7-4), (<2,>=1-21-1)
            match = re.match("(.+) \([^()]*\)", depend)
            if match:
                name = match.group(1)
                return '{}[${{PYTHON_USEDEP}}]'.format(get_package_name(name, default_category))
            else:
                return '{}[${{PYTHON_USEDEP}}]'.format(get_package_name(depend, default_category))

def get_iuse_and_depend(project, default_category):
    requires = project['info']['requires_dist']
    simple = []
    uses = defaultdict(list)
    if requires == None:
        return ''
    for req in requires:
        for rm in removals:
            if rm in req:
                break
        else:
            match = re.match("(.+); extra == '(.+)'", req)
            if match:
                name = match.group(1).strip()
                use = match.group(2)
                if use in use_blackhole:
                    continue
                uses[use].append(convert_dependency(name, default_category))
            else:
                match = re.match('(.+); python_version < "(.+)"', req)
                if match:
                    name = match.group(1).strip()
                    if not name.startswith('backports'):
                        # we don't need backports for python3
                        simple.append(convert_dependency(name, default_category))
                else:
                    simple.append(convert_dependency(req.strip(), default_category))

    use_res = []
    for use in uses:
        use_res.append('{}? ( {} )'.format(use, '\n\t\t'.join(uses[use])))
    iuse = 'IUSE="{}"'.format(" ".join(uses.keys()))
    return iuse + '\n' + 'RDEPEND="' + '\n\t'.join(simple + use_res) + '"'

# TODO: format the related code to purge this dependency
import xmltodict

def upstream_has_pypi(metadata_dict):
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
    len_old = len(existing_packages)
    cate_pkg_match = re.compile(f"{repo}/(.*)/(.+)/metadata.xml")

    for pkg_metadata in glob.glob(f'{repo}/**/metadata.xml', recursive=True):
        match = cate_pkg_match.match(pkg_metadata)
        if match:
            pypi_id = upstream_has_pypi(xmltodict.parse(open(pkg_metadata).read()))
            if pypi_id:
                existing_packages[regularize_package_name(pypi_id)] = [match.group(1), match.group(2)]

    print(f'Found {len(existing_packages) - len_old} packages in {repo}')

# TODO: update maintainer
# TODO: accept description
def generate_metadata_if_not_exists(metadata_path, pypi_id):
    if not metadata_path.exists():
        metadata =  f'''<?xml version="1.0" encoding="UTF-8"?>
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
    <remote-id type="pypi">{pypi_id}</remote-id>
  </upstream>
</pkgmetadata>
'''
        return open(metadata_path, 'w').write(metadata)

def generate(package, args):
    print('Generating {} to {}'.format(package, args.repo))
    resp = requests.get("https://pypi.org/pypi/{}/json".format(package))
    body = json.loads(resp.content)

    # TODO: parse it from args
    default_category = DEFAULT_CATEGORY
    #
    pypi_id = body['info']['name']
    package = regularize_package_name(pypi_id)
    versions = get_project_python_versions(body)
    compat = ' '.join(['python' + version.replace('.','_') for version in versions])
    print('Python versions', versions)
    print('Homepage', body['info']['home_page'])
    print('Description', body['info']['summary'])
    license = body['info']['license']
    if license in license_mapping:
        license = license_mapping[license]
    print('License', license)
    print('Version', body['info']['version'])
    iuse_and_depend = get_iuse_and_depend(body, default_category)
    print('IUSE and Depend', iuse_and_depend)

    # get category of the package
    category = existing_packages.get(package, default_category)[0]

    dir = Path(args.repo) / category / package
    path = dir / "{}-{}.ebuild".format(package, body['info']['version'])
    print('Writing to', path)
    dir.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        content = '# Copyright 1999-2021 Gentoo Authors\n'
        content += '# Distributed under the terms of the GNU General Public License v2\n\n'
        content += 'EAPI=7\n\n'
        content += 'PYTHON_COMPAT=( {} )\n\n'.format(compat)
        content += 'inherit distutils-r1\n\n'
        content += 'DESCRIPTION="{}"\n'.format(body['info']['summary'])
        content += 'SRC_URI="mirror://pypi/${PN:0:1}/${PN}/${P}.tar.gz"\n'
        content += 'HOMEPAGE="{}"\n\n'.format(body['info']['home_page'])
        content += 'LICENSE="{}"\n'.format(body['info']['license'])
        content += 'SLOT="0"\n'
        content += 'KEYWORDS="~amd64"\n\n'
        content += iuse_and_depend
        content += '\ndistutils_enable_tests pytest\n'

        f.write(content)

    generate_metadata_if_not_exists(dir / "metadata.xml", pypi_id)

    if args.repoman:
        os.system('cd %s && repoman manifest' % (dir))
        
    # regularize_package_name() is called before
    # update existing_packages anyway
    existing_packages[package] = [category, package]
    if package in missing_packages:
        missing_packages.remove(package)
    
    if args.recursive:
        for pkg in list(missing_packages):
            if pkg not in existing_packages:
                generate(pkg, args)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--repo', help='set repo directory', default='../gentoo-localrepo')
    parser.add_argument('-v', '--verbose', action='store_true', help='enable verbose logging')
    parser.add_argument('-R', '--recursive', action='store_true', help='generate ebuild recursively')
    parser.add_argument('-p', '--repoman', action='store_true', help='run "repoman manifest" after generation')
    parser.add_argument('packages', nargs='+')
    args = parser.parse_args()

    # TODO: format it later
    import portage
    eroot = '/'
    repos = portage.db[eroot]["vartree"].settings.repositories.prepos_order

    for repo in repos:
        find_packages(portage.db[eroot]["vartree"].settings.repositories.treemap.get(repo))

    # setup repo structure
    metadata = Path(args.repo) / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    with (metadata / "layout.conf").open('w') as f:
        f.write("masters = gentoo\nauto-sync = false\n")

    for package in args.packages:
        generate(package, args)

if __name__ == "__main__":
    main()
