from typing import List, Tuple, Set, Dict, Callable

import argparse
import ast
import sys
from pathlib import Path

VERSION = '0.1.0.0'

QModName = Tuple[str, ...]


def output_dependencies(dependencies: Dict[QModName, Set[QModName]]):
    def render(qn: QModName) -> str:
        return '.'.join(qn)

    for src in dependencies.keys():
        for dst in dependencies[src]:
            print(render(src) + ' ' + render(dst))


def dbg(packages: Set[QModName], src_dir_targets: Set[QModName], extra_targets: Set[QModName]):
    sys.stderr.writelines([
        'packages: ' + str(packages),
        '\n',
        'src_dir_targets: ' + str(src_dir_targets),
        '\n',
        'extra_targets: ' + str(extra_targets),
        '\n',
    ])


def main(src_dir: Path, extra_targets: Set[QModName]):
    packages, src_dir_targets, mod_files = read_input_paths(src_dir)
    all_targets = src_dir_targets.union(extra_targets)
    #dbg(packages, src_dir_targets, extra_targets)
    deps_reader = DependenciesReader(src_dir, all_targets, packages)
    dependencies = deps_reader.read(mod_files)
    output_dependencies(dependencies)


class DependenciesReader:
    def __init__(self,
                 src_dir: Path,
                 targets: Set[QModName],
                 packages: Set[QModName],
                 ):
        self.src_dir = src_dir
        self.targets = targets
        self.packages = packages

    def read(self, mod_files: List[Path]) -> Dict[QModName, Set[QModName]]:
        ret_val = dict()
        for mod_file in mod_files:
            src, dst = self._deps_of_file(mod_file)
            ret_val[src] = dst

        return ret_val

    def _deps_of_file(self, mod_file: Path) -> Tuple[QModName, Set[QModName]]:
        src_mod_name = mod_name_from_path(mod_file.relative_to(self.src_dir))
        mod_file_source = mod_file.read_text()
        imported_modules = self._extract_imports(mod_file_source)
        return src_mod_name, set([qname for qname in imported_modules if self._is_target(qname)])

    def _extract_imports(self, mod_file_source: str) -> List[QModName]:
        the_ast = ast.parse(mod_file_source)
        imports_extractor = ImportsExtractor(self.src_dir, self._is_target, self.packages)
        imports_extractor.visit(the_ast)
        return imports_extractor.output

    def _is_target(self, module: QModName) -> bool:
        for t in self.targets:
            if module[:len(t)] == t:
                return True
        return False


class ImportsExtractor(ast.NodeVisitor):
    def __init__(self,
                 src_dir: Path,
                 is_target: Callable[[QModName], bool],
                 packages: Set[QModName],
                 ):
        self._src_dir = src_dir
        self._is_target = is_target
        self._packages = packages
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
        if not self._is_target(base):
            return
        if base in self._packages:
            rel_names = [mod_name_from_str(name.name) for name in node.names]
            self.output += [
                base + rel_name
                for rel_name in rel_names
            ]
        else:
            self.output.append(base)

    def _handle_relative(self, node: ast.ImportFrom):
        pass


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
