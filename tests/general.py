import sys
import os
from os.path import abspath, basename, join, splitext
from tempfile import NamedTemporaryFile, mkdtemp
from shutil import rmtree

from vermin import combine_versions, InvalidVersionException, detect_paths,\
  probably_python_file, Processor, process_individual, reverse_range, dotted_name, main, Config

from .testutils import VerminTest, visit, detect, current_version

def touch(fld, name):
  filename = join(fld, name)
  fp = open(filename, mode="w")
  fp.close()
  return filename

class VerminGeneralTests(VerminTest):
  def __init__(self, methodName):
    super(VerminGeneralTests, self).__init__(methodName)
    self.config = Config.get()

  def setUp(self):
    self.config.reset()

  def tearDown(self):
    self.config.reset()

  def test_format(self):
    # Empty field name requires 2.7+
    visitor = visit("print('{}'.format(42))")
    self.assertTrue(visitor.format27())

    # Non-empty field name requires 2.6+
    visitor = visit("print('{0}'.format(42))")
    self.assertFalse(visitor.format27())

  def test_strftime_directives(self):
    visitor = visit("from datetime import datetime\ndatetime.now().strftime('%A %d. %B %Y')")
    self.assertOnlyIn(("A", "d", "B", "Y"), visitor.strftime_directives())
    visitor = visit("from datetime import datetime\ndatetime.strptime('2018', '%Y')")
    self.assertOnlyIn("Y", visitor.strftime_directives())

  def test_modules(self):
    visitor = visit("import ast\nimport sys, argparse\nfrom os import *")
    self.assertOnlyIn(("ast", "sys", "argparse", "os"), visitor.modules())

  def test_member_class(self):
    visitor = visit("from abc import ABC")
    self.assertOnlyIn("abc.ABC", visitor.members())
    visitor = visit("import abc\nclass a(abc.ABC): pass")
    self.assertOnlyIn("abc.ABC", visitor.members())

  def test_member_function(self):
    visitor = visit("from sys import exc_clear")
    self.assertOnlyIn("sys.exc_clear", visitor.members())

  def test_member_constant(self):
    visitor = visit("from sys import version_info")
    self.assertOnlyIn("sys.version_info", visitor.members())

  def test_member_kwargs(self):
    visitor = visit("from os import open\nfd = open(dir_fd = None)")
    self.assertOnlyIn([("os.open", "dir_fd")], visitor.kwargs())
    visitor = visit("fd = open(dir_fd = None)")
    self.assertOnlyIn([("open", "dir_fd")], visitor.kwargs())

  def test_probably_python_file(self):
    tmp_fld = mkdtemp()

    self.assertTrue(probably_python_file(touch(tmp_fld, "test.py")))
    self.assertTrue(probably_python_file(touch(tmp_fld, "test.pyw")))
    self.assertFalse(probably_python_file(touch(tmp_fld, "test.pyc")))

    # Empty file isn't python.
    f = touch(tmp_fld, "test")
    self.assertFalse(probably_python_file(f))

    # Magic line.
    with open(f, mode="w") as fp:
      fp.write("#!/usr/bin/env python\n")
    self.assertTrue(probably_python_file(f))

    # Binary file isn't python code.
    f = touch(tmp_fld, "binary")
    with open(f, mode="wb") as fp:
      fp.write(b"\x80\x89\x90")
    self.assertFalse(probably_python_file(f))

    rmtree(tmp_fld)

  def test_detect_paths(self):
    paths = detect_paths([abspath("vermin")])
    self.assertEqual(13, len(paths))

  def test_detect_hidden_paths(self):
    tmp_fld = mkdtemp()
    files = [touch(tmp_fld, ".test.py"), touch(tmp_fld, "test.py"), touch(tmp_fld, ".test2.py"),
             touch(tmp_fld, "test2.py")]

    paths = detect_paths([tmp_fld], hidden=False)
    without_dot = [files[1], files[3]]
    self.assertEqualItems(without_dot, paths)

    paths2 = detect_paths([tmp_fld], hidden=True)
    self.assertEqualItems(files, paths2)

    rmtree(tmp_fld)

  # Files directly specified at depth 0 should be accepted in any case, even if not with .py or
  # heuristics, but extensions and heuristics must be used further down.
  def test_detect_vermin_paths_directly(self):
    tmp_fld = mkdtemp()

    # Won't be picked by heuristics.
    f = touch(tmp_fld, "no-shebang")
    with open(f, mode="w") as fp:
      fp.write("print('this is code')")

    paths = detect_paths([tmp_fld])
    self.assertEmpty(paths)

    paths = detect_paths([join(tmp_fld, "no-shebang")])
    self.assertEqual(paths, [f])

    rmtree(tmp_fld)

  # Ensure all proper Python source code files are detected: py, py3, pyw, pyj, pyi
  def test_detect_vermin_paths_all_exts(self):
    tmp_fld = mkdtemp()

    exts = ('py', 'py3', 'pyw', 'pyj', 'pyi')
    for ext in exts:
      f = touch(tmp_fld, "code." + ext)
      with open(f, mode="w") as fp:
        fp.write("print('this is code')")

    found_exts = set()
    for path in detect_paths([tmp_fld]):
      _, ext = splitext(path)
      found_exts.add(ext[1:])
    self.assertEqualItems(found_exts, exts)

    rmtree(tmp_fld)

  # Ensure all non-Python source code files are not detected: pyc, pyd, pxd, pyx, pyo
  def test_detect_vermin_paths_no_invalid_exts(self):
    tmp_fld = mkdtemp()

    exts = ("pyc", "pyd", "pxd", "pyx", "pyo")
    for ext in exts:
      f = touch(tmp_fld, "code." + ext)
      with open(f, mode="w") as fp:
        fp.write("print('this is code')")

    found_exts = set()
    for path in detect_paths([tmp_fld]):
      _, ext = splitext(path)
      found_exts.add(ext[1:])
    self.assertEmpty(found_exts)

    rmtree(tmp_fld)

  def test_detect_vermin_min_versions(self):
    paths = detect_paths([abspath("vermin")])
    processor = Processor()
    (mins, incomp, unique_versions, backports) = processor.process(paths)
    self.assertOnlyIn(((2, 7), (3, 0)), mins)
    self.assertEmpty(backports)

  def test_combine_versions(self):
    with self.assertRaises(AssertionError):
      combine_versions([None], [None, None])
    self.assertEqual([(2, 0), (3, 1)], combine_versions([(2, 0), (3, 0)], [(2, 0), (3, 1)]))
    self.assertEqual([(2, 0), (3, 1)], combine_versions([2, (3, 0)], [(2, 0), 3.1]))
    self.assertEqual([(2, 0), (3, 1)], combine_versions([(2, 0), 3], [2, 3.1]))
    self.assertEqual([(2, 0), (3, 1)], combine_versions([2.0, 3.0], [2.0, 3.1]))
    self.assertEqual([(2, 1), (3, 0)], combine_versions([2.1, 3.0], [2.0, 3.0]))
    self.assertEqual([None, (3, 0)], combine_versions([2.0, 3.0], [None, 3.0]))
    self.assertEqual([(2, 0), None], combine_versions([2.0, None], [2.0, 3.0]))
    self.assertEqual([None, None], combine_versions([2.0, 3.0], [None, None]))
    self.assertEqual([None, None], combine_versions([None, None], [2.0, 3.0]))
    with self.assertRaises(InvalidVersionException):
      combine_versions([2.0, None], [None, 3.0])
    with self.assertRaises(InvalidVersionException):
      combine_versions([None, 3.0], [2.0, None])
    self.assertEqual([(0, 0), (3, 0)], combine_versions([0, 3.0], [0, 3.0]))
    self.assertEqual([(2, 0), (3, 0)], combine_versions([0, 3.0], [2.0, 3.0]))
    self.assertEqual([(2, 0), (3, 0)], combine_versions([2.0, 3.0], [0, 3.0]))
    self.assertEqual([(2, 0), (3, 0)], combine_versions([2.0, 0], [2.0, 3.0]))
    self.assertEqual([(2, 0), (3, 0)], combine_versions([2.0, 3.0], [2.0, 0]))

  def test_detect_min_version(self):
    self.assertEqual([(2, 6), (3, 0)], detect("import abc"))

    # (2.6, 3.0) vs. (2.7, 3.2) = (2.7, 3.2)
    self.assertEqual([(2, 7), (3, 2)], detect("import abc, argparse"))

    # (2.6, 3.0) vs. (None, 3.4) = (None, 3.4)
    self.assertEqual([None, (3, 4)], detect("import abc\nfrom abc import ABC"))

    # (2.0, None) vs. (2.0, 3.0) = (2.0, None)
    self.assertEqual([(2, 0), None], detect("import repr\nfrom sys import getdefaultencoding"))

    # (2.0, None) vs. (None, 3.0) = both exclude the other major version -> exception!
    with self.assertRaises(InvalidVersionException):
      detect("import copy_reg, http")

  def test_reverse_range(self):
    self.assertEqual(list(reverse_range([1, 2, 3])), [2, 1, 0])
    self.assertEqual(list(reverse_range([1, 2])), [1, 0])
    self.assertEqual(list(reverse_range([])), [])

  def test_dotted_name(self):
    self.assertEqual(dotted_name(["hello", "world"]), "hello.world")
    self.assertEqual(dotted_name(["foo", ["bar", "baz"], "boom"]), "foo.bar.baz.boom")
    self.assertEqual(dotted_name(["foo", ("bar", "baz"), "boom"]), "foo.bar.baz.boom")
    self.assertEqual(dotted_name([1, 2, 3]), "1.2.3")
    self.assertEqual(dotted_name("right"), "right")
    self.assertEqual(dotted_name(["hello", None, "world"]), "hello.world")
    self.assertEqual(dotted_name(["foo", (None, "baz"), None]), "foo.baz")

  def test_assign_rvalue_attribute(self):
    self.assertEqual([None, (3, 3)], detect("import bz2\nv = bz2.BZ2File\nv.writable"))

  def test_user_defined(self):
    visitor = visit("def hello(): pass\nhello2()\nclass foo(): pass")
    self.assertOnlyIn(["hello", "foo"], visitor.user_defined())

  def test_ignore_members_when_user_defined_funcs(self):
    # `next()` was builtin from 2.6.
    visitor = visit("def next(): pass\nnext()")
    self.assertOnlyIn("next", visitor.user_defined())
    self.assertEmpty(visitor.members())

  def test_ignore_members_when_user_defined_classes(self):
    # `bytearray` was builtin from 2.6.
    visitor = visit("class bytearray: pass\nba = bytearray()")
    self.assertOnlyIn(["bytearray", "ba"], visitor.user_defined())
    self.assertEmpty(visitor.members())

  def test_ignore_modules_when_user_defined_funcs(self):
    # This test relies on the rule for "SimpleXMLRPCServer" module.

    # Ignore module due to class def.
    visitor = visit("import SimpleXMLRPCServer\n"
                    "def SimpleXMLRPCServer(): pass\n"
                    "src = SimpleXMLRPCServer()")
    self.assertOnlyIn(["SimpleXMLRPCServer", "src"], visitor.user_defined())
    self.assertEmpty(visitor.modules())

  def test_ignore_modules_when_user_defined_classes(self):
    # This test relies on the rule for "SimpleXMLRPCServer" module.

    # Ignore module due to class def.
    visitor = visit("import SimpleXMLRPCServer\n"
                    "class SimpleXMLRPCServer: pass\n"
                    "src = SimpleXMLRPCServer()")
    self.assertOnlyIn(["SimpleXMLRPCServer", "src"], visitor.user_defined())
    self.assertEmpty(visitor.modules())

  def test_mod_inverse_pow(self):
    # All arguments must be ints.
    visitor = visit("pow(1.1, -1, 3)")
    self.assertFalse(visitor.modular_inverse_pow())
    visitor = visit("pow(1, -1.0, 3)")
    self.assertFalse(visitor.modular_inverse_pow())
    visitor = visit("pow(1, -1, 3.0)")
    self.assertFalse(visitor.modular_inverse_pow())

    # The second argument can be negative to yield modular inverse calculation.
    visitor = visit("pow(1, -2, 3)")
    self.assertTrue(visitor.modular_inverse_pow())
    self.assertOnlyIn((3, 8), visitor.minimum_versions())

  def test_main_no_args(self):
    # Print usage and exit with code 1.
    with self.assertRaises(SystemExit) as ex:
      main()
    self.assertEqual(ex.exception.code, 1)

  def test_main_full_usage(self):
    # Print full usage and exit with code 0.
    with self.assertRaises(SystemExit) as ex:
      sys.argv = [sys.argv[0], "--help"]
      main()
    sys.argv = [sys.argv[0]]
    self.assertEqual(ex.exception.code, 0)

  def test_main_print_version(self):
    # Print version and exit with code 0.
    with self.assertRaises(SystemExit) as ex:
      sys.argv = [sys.argv[0], "--version"]
      main()
    sys.argv = [sys.argv[0]]
    self.assertEqual(ex.exception.code, 0)

  def test_main_no_paths(self):
    # The path doesn't exist and isn't a .py file which means no paths are detected.
    with self.assertRaises(SystemExit) as ex:
      sys.argv = [sys.argv[0], "nonexistentfilethatisntpy"]
      main()
    sys.argv = [sys.argv[0]]
    self.assertEqual(ex.exception.code, 1)

  def test_main_no_rules_hit(self):
    # Python file that doesn't hit any rules should exit successfully.
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.close()
    with self.assertRaises(SystemExit) as ex:
      sys.argv = [sys.argv[0], fp.name]
      main()
    os.remove(fp.name)
    sys.argv = [sys.argv[0]]
    self.assertEqual(ex.exception.code, 0)

  def test_main_target_not_met(self):
    # Ensure exit code 1 when target isn't met.
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.close()
    with self.assertRaises(SystemExit) as ex:
      sys.argv = [sys.argv[0], "-t=3.0", fp.name]
      main()
    os.remove(fp.name)
    sys.argv = [sys.argv[0]]
    self.assertEqual(ex.exception.code, 1)

  def test_process_file_not_Found(self):
    if current_version() >= 3.0:
      exc = FileNotFoundError
    else:
      exc = Exception
    with self.assertRaises(exc):
      process_individual(("nonexistent", self.config))

  def test_process_runtests_py(self):
    proc_res = process_individual((sys.argv[0], self.config))
    self.assertEqual(basename(proc_res.path), "runtests.py")
    self.assertEqual(proc_res.mins, [(2, 7), (3, 1)])
    self.assertEmpty(proc_res.text)
    self.assertEmpty(proc_res.bps)

  def test_process_syntax_error(self):
    # Syntax error triggers minimum versions [0, 0].
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b'(')  # SyntaxError: unexpected EOF while parsing
    fp.close()
    proc_res = process_individual((fp.name, self.config))
    self.assertEqual(proc_res.mins, [(0, 0), (0, 0)])
    self.assertEmpty(proc_res.text)
    self.assertEmpty(proc_res.bps)
    os.remove(fp.name)

  def test_process_value_error(self):
    # (Py3) ValueError: source code string cannot contain null bytes
    # (Py2) TypeError: compile() expected string without null bytes
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b'\0')
    fp.close()
    proc_res = process_individual((fp.name, self.config))
    self.assertEqual(proc_res, None)
    os.remove(fp.name)

  def test_process_invalid_versions(self):
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b"long(42)\n")  # long is a v2 feature: 2.0 !3
    fp.write(b"breakpoint()\n")  # breakpoint(): !2, 3.7
    fp.close()
    proc_res = process_individual((fp.name, self.config))
    self.assertEqual(proc_res.mins, None)
    self.assertTrue(proc_res.text.startswith("Versions could not be combined"))
    self.assertEmpty(proc_res.bps)
    os.remove(fp.name)

  def test_process_file_using_backport(self):
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b"import typing\n")
    fp.close()
    proc_res = process_individual((fp.name, self.config))
    self.assertEmpty(proc_res.text)
    self.assertEqualItems(["typing"], proc_res.bps)
    os.remove(fp.name)

  def test_processor_value_error(self):
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b"\0")
    fp.close()
    paths = [fp.name]
    processor = Processor()
    (mins, incomp, unique_versions, backports) = processor.process(paths)
    self.assertEqual(mins, [(0, 0), (0, 0)])
    self.assertFalse(incomp)
    self.assertEmpty(unique_versions)
    self.assertEmpty(backports)
    os.remove(fp.name)

  def test_processor_incompatible(self):
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b"import Queue\n")  # 2.0, !3
    fp.write(b"import builtins\n")  # !2, 3.0
    fp.close()
    paths = [fp.name]
    processor = Processor()
    (mins, incomp, unique_versions, backports) = processor.process(paths)
    self.assertEqual(mins, [(0, 0), (0, 0)])
    self.assertTrue(incomp)
    self.assertEmpty(unique_versions)
    self.assertEmpty(backports)
    os.remove(fp.name)

  def test_processor_separately_incompatible(self):
    paths = []
    codes = [
      b"import Queue\n",  # 2.0, !3
      b"import builtins\n",  # !2, 3.0
    ]
    for code in codes:
      fp = NamedTemporaryFile(suffix=".py", delete=False)
      fp.write(code)
      fp.close()
      paths.append(fp.name)

    processor = Processor()
    (mins, incomp, unique_versions, backports) = processor.process(paths)
    self.assertEqual(mins, [(2, 0), None])  # Because the Queue file is analyzed first.
    self.assertTrue(incomp)
    self.assertEqual(unique_versions, [(2, 0), (3, 0)])
    self.assertEmpty(backports)

    for path in paths:
      os.remove(path)

  def test_processor_indent_show_output_text(self):
    self.config.set_verbose(4)  # Ensure output text.
    fp = NamedTemporaryFile(suffix=".py", delete=False)
    fp.write(b"def foo():\n\tpass\n")
    fp.write(b"foo()\n")  # L3: Ignoring member 'foo' because it's user-defined!
    fp.write(b"print('hello')\n")  # print(expr) requires 2+ or 3+
    fp.close()
    paths = [fp.name]
    processor = Processor()
    (mins, incomp, unique_versions, backports) = processor.process(paths)

    if current_version() >= 3.0:
      self.assertEqual(mins, [(2, 0), (3, 0)])
      self.assertEqual(unique_versions, [(2, 0), (3, 0)])
    else:
      self.assertEqual(mins, [(2, 0), (0, 0)])
      self.assertEqual(unique_versions, [(2, 0)])

    self.assertFalse(incomp)
    self.assertEmpty(backports)
    os.remove(fp.name)
