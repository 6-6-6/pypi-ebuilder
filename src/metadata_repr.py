"""
This file represents the intermedia metadata
"""

### TODO: do I really need this lock?
from threading import RLock

class PkgMetadata:

    def __init__(self,
                 pypi_id,
                 portage_cate, portage_name, portage_version=None,
                 portage_lic=None):
        # pypi id (str): the related pypi id
        self.pypi_id = pypi_id
        #
        self.portage_cate = portage_cate
        self.portage_name = portage_name
        # these two are not critical
        self.portage_version = portage_version
        self.portage_lic = portage_lic
        #
    
    def add_descriptions(self, short_desc, long_desc):
        self.short_desc = short_desc
        self.long_desc = long_desc
    
    def add_homepage(self, homepage):
        self.homepage = homepage
    
    def parse_deps(self, dep_dict):
        # import it here to resolve circular import....
        from .pypi_parser import PYPIParser, PYPICommunicator
        dep_str = "\n"
        for pypi_id, version_hint in dep_dict["_default"]:
            cate, pn, exist = PYPIParser.catepn(pypi_id)
            # dep string
            if version_hint[0] != None:
                dep_str += f"\t{version_hint[0]}{cate}/{pn}-{version_hint[1]}[${{PYTHON_USEDEP}}]\n"
            else:
                dep_str += f"\t{cate}/{pn}[${{PYTHON_USEDEP}}]\n"
            # add missing to todo list
            ## TODO:
            if not exist:
                t = PYPICommunicator()
                t.test(pypi_id)
        for key, val in dep_dict.items():
            if key != "_default":
                dep_str += f"\t{key}? (\n"
                for pypi_id, version_hint in val:
                    cate, pn, exist = PYPIParser.catepn(pypi_id)
                    if version_hint[0] != None:
                        dep_str += f"\t\t{version_hint[0]}{cate}/{pn}-{version_hint[1]}[${{PYTHON_USEDEP}}]\n"
                    else:
                        dep_str += f"\t\t{cate}/{pn}[${{PYTHON_USEDEP}}]\n"
                dep_str += "\t)\n"
        #
        self.dep_dict = dep_dict
        self.dep_str = dep_str
        self.iuse = set(dep_dict.keys())
        self.iuse.remove("_default")

    def export_dict(self):
        return {
            "short_desc": self.short_desc,
            "long_desc": self.long_desc,
            "homepage": self.homepage,
            "lic_string": self.portage_lic,
            "dep_string": self.dep_str,
            "pypi_id": self.pypi_id,
            "iuse": " ".join(self.iuse)
            }


class ToBeGeneratedEbuilds:
    lock = RLock()
    # pypi_id: PkgMetadata
    payload = {}

        