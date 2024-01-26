from src import pypi_parser
from src import portage_parser
from src import ebuild_writer
import portage
from pathlib import Path

# parse
if 1:
    import portage
    # TODO: find out what to do if portage.db has multiple keys
    eroot = next(iter(portage.db.keys()))
    repo_names = portage.db[eroot]["vartree"].settings.repositories.prepos_order
    repos = []
    for name in repo_names:
        repos.append(portage.db[eroot]["vartree"].settings.repositories.treemap.get(name))
    
    for repo in repos:
        portage_parser.find_packages(repo)

#for k, v in pypi_parser.PYPIParser.PN_database.items():
#    print(k,v)

t1 = pypi_parser.PYPICommunicator()
t1.test("spark-utils")

print()

with pypi_parser.ToBeGeneratedEbuilds.lock:
    print(pypi_parser.ToBeGeneratedEbuilds.payload)
    for pypi_id, my_metadata in pypi_parser.ToBeGeneratedEbuilds.payload.items():
        ebuild_writer.generate(Path("test"),
                       pypi_id,
                       my_metadata)