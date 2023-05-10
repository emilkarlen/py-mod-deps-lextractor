from typing import List, Tuple, Set, Dict, Callable, Sequence, Iterable, Optional

import argparse
import ast
import sys
import itertools
from pathlib import Path

VERSION = '0.1.0.0'

Identifier = str
QModName = Tuple[Identifier, ...]


def render_mod_name(qname: QModName) -> str:
    return '.'.join(qname)


def output_dependencies(dependencies: Dict[QModName, Set[QModName]]):
    for src in dependencies.keys():
        for dst in dependencies[src]:
            print(render_mod_name(src) + ' ' + render_mod_name(dst))


class ModuleInfo:
    def __init__(self, source_file: Path):
        self.source_file = source_file


class QModuleInfo:
    def __init__(self, qname: QModName, info: ModuleInfo, parents: List['PackageInfo']):
        self.qname = qname
        self.info = info
        self.parents = parents

    def __str__(self) -> str:
        return '.'.join(self.qname)


class PackageInfo:
    def __init__(self,
                 modules: Dict[Identifier, ModuleInfo],
                 packages: Dict[Identifier, 'PackageInfo'],
                 ):
        self.packages = packages
        self.modules = modules
        self.names = set(itertools.chain(modules.keys(), packages.keys()))

    def is_root_of(self, qname: QModName) -> bool:
        return qname[0] in self.names

    def iter_modules(self) -> Iterable[QModuleInfo]:
        yield from self._iter_modules((), [])

    def _iter_modules(self, parent_qname: QModName, parents: List['PackageInfo']) -> Iterable[QModuleInfo]:
        for ident, m_info in self.modules.items():
            yield QModuleInfo(parent_qname + (ident,), m_info, parents)
        for ident, p_info in self.packages.items():
            yield from p_info._iter_modules(parent_qname + (ident,), [self] + parents)

    @staticmethod
    def of_dir(src_dir: Path) -> 'PackageInfo':
        modules: Dict[Identifier, ModuleInfo] = dict()
        packages: Dict[Identifier, 'PackageInfo'] = dict()

        for p in src_dir.iterdir():
            if p.is_file() and p.suffix == '.py' and p.name != '__init__.py':
                modules[p.with_suffix('').name] = ModuleInfo(p)
            elif p.is_dir() and (p / '__init__.py').is_file():
                packages[p.name] = PackageInfo.of_dir(p)

        return PackageInfo(modules, packages)


class DependenciesReader:
    def __init__(self, root_dir_info: PackageInfo):
        self.root_dir_info = root_dir_info

    def read(self) -> Dict[QModName, Set[QModName]]:
        ret_val = dict()
        for mod_file_info in self.root_dir_info.iter_modules():
            src, dst = self._deps_of_file(mod_file_info)
            ret_val[src] = dst

        return ret_val

    def _deps_of_file(self, module: QModuleInfo) -> Tuple[QModName, Set[QModName]]:
        imported_modules = self._extract_imports(module)
        return module.qname, set([qname for qname in imported_modules if self._is_target(qname)])

    def _extract_imports(self, module: QModuleInfo) -> List[QModName]:
        mod_file_source = module.info.source_file.read_text()
        the_ast = ast.parse(mod_file_source)
        imports_extractor = ImportsExtractor(self.root_dir_info, module)
        imports_extractor.visit(the_ast)
        return imports_extractor.output

    def _is_target(self, module: QModName) -> bool:
        return self.root_dir_info.is_root_of(module)


class ImportsExtractor(ast.NodeVisitor):
    def __init__(self,
                 root_dir_info: PackageInfo,
                 module: QModuleInfo,
                 ):
        self._root_dir_info = root_dir_info
        self._module = module
        self.output = []

    def visit_Import(self, node: ast.Import):
        self.output += [mod_name_from_str(n.name) for n in node.names]

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level == 0:
            self._handle_absolute(node)
        else:
            self._handle_relative(node)

    def _handle_absolute(self, node: ast.ImportFrom):
        base = mod_name_from_str(node.module)
        if not self._root_dir_info.is_root_of(base):
            return
        mb_package = self._lookup_package(base)
        if mb_package is not None:
            idents = self._star_or_non_star_names(node.names, mb_package)
            self.output += [
                base + (ident,)
                for ident in idents
            ]
        else:
            self.output.append(base)

    @staticmethod
    def _star_or_non_star_names(imported: List[ast.alias],
                                package_info: PackageInfo,
                                ) -> Iterable[Identifier]:
        if len(imported) == 1 and imported[0].name == '*':
            return package_info.names
        else:
            return [name.name for name in imported]

    def _handle_relative(self, node: ast.ImportFrom):
        pass

    def _lookup_package(self, qname: QModName) -> Optional[PackageInfo]:
        pkg_info = self._root_dir_info
        for ident in qname:
            pkg_info = pkg_info.packages.get(ident)
            if pkg_info is None:
                break
        return pkg_info


def mod_name_from_path(p: Path) -> QModName:
    return tuple(p.with_suffix('').parts)


def mod_name_from_str(name: str) -> QModName:
    return tuple(name.split('.'))


def read_input_paths(src_dir: Path) -> Tuple[Set[QModName], Set[QModName], List[Path]]:
    def pkg_name_of_init_file(p: Path) -> QModName:
        return tuple(p.parts[:-1])

    packages = set()
    targets = set()
    mod_files = []
    for py_path in src_dir.glob('**/*.py'):
        rel_py_path = py_path.relative_to(src_dir)
        if rel_py_path.name == '__init__.py':
            pkg = pkg_name_of_init_file(rel_py_path)
            packages.add(pkg)
            if len(pkg) == 1:
                targets.add(pkg)
        else:
            mod_files.append(py_path)
        if len(rel_py_path.parts) == 1:
            targets.add(mod_name_from_path(rel_py_path))

    return packages, targets, mod_files


def dbg(packages: Set[QModName], src_dir_targets: Set[QModName], extra_targets: Set[QModName],
        root_dir_info: PackageInfo, mod_files: List[Path]):
    sys.stderr.writelines([
        'packages: ' + str(packages),
        '\n',
        'src_dir_targets: ' + str(src_dir_targets),
        '\n',
        'extra_targets: ' + str(extra_targets),
        '\n',
        'module files: \n   ' + '\n   '.join([str(fn) for fn in mod_files]),
        '\n',
        'root PackageInfo\n',
        '  modules : {}\n'.format(list(root_dir_info.modules.keys())),
        '  packages: {}\n'.format(list(root_dir_info.packages.keys())),
        '\n',
        'modules iter: \n' + '\n'.join([render_mod_name(mi.qname) for mi in root_dir_info.iter_modules()]),
        '\n',
        '---------------------------------',
        '\n',
    ])


def main(src_dir: Path, extra_targets: Set[QModName]):
    root_dir_info = PackageInfo.of_dir(src_dir)

    packages, src_dir_targets, mod_files = read_input_paths(src_dir)
    all_targets = src_dir_targets.union(extra_targets)
    # dbg(packages, src_dir_targets, extra_targets, root_dir_info, mod_files)
    deps_reader = DependenciesReader(root_dir_info)
    dependencies = deps_reader.read()
    output_dependencies(dependencies)


def cli_parse() -> Tuple[Path, Set[QModName]]:
    path_meta_var = 'PATH'
    parser = argparse.ArgumentParser(description=HELP)
    parser.add_argument(
        'py_path',
        nargs='?',
        default=None,
        type=Path,
        action='store',
        metavar=path_meta_var,
        help='Directory containing Python source files, just like a PYTHONPATH entry'
    )
    parser.add_argument(
        "--target", '-t',
        action='append',
        default=[],
        metavar='PACKAGE',
        help='Imports of modules in this package are reported as dependencies, '
             'in addition to those in the given {} dir.'.format(path_meta_var)
    )
    parser.add_argument(
        "--version",
        action='store_true',
        help="Show program version and exit",
    )

    args = parser.parse_args()

    if args.version:
        show_version_and_exit()

    path = args.py_path
    if path is None:
        exit_error('Missing ' + path_meta_var)
    elif not path.is_dir():
        exit_error('Not an existing dir: ' + str(path))

    extra_targets = set([mod_name_from_str(t) for t in args.target])
    return path, extra_targets


def exit_error(msg: str):
    sys.stderr.write(sys.argv[0] + ': ' + msg)
    sys.stderr.write('\n')
    sys.exit(1)


def show_version_and_exit():
    print(VERSION)
    sys.exit(0)


src_dir_opt = '--path'

HELP = """\
Generates a list of module dependencies of Python source files

Python source file names are read from stdin.

The Python source file names must be relative the dir given by {src_dir_opt}.""".format(
    src_dir_opt=src_dir_opt
)

if __name__ == '__main__':
    main(*cli_parse())
