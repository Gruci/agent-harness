"""Framework packs: web and UI gate declarations come from the selected pack; an unselected pack is reported, never silently passed."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from kernel import context, framework, linters, pack_check, profile, runner
from kernel.gates import orphan_api

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_test_support import TemporaryRootTestCase   # noqa: E402  (site-packages 의 `tests` 패키지가 tests.* 를 가린다)

UILINT = context.ROOT / "tests" / "fixtures" / "uilint"

# 테스트 픽스처 서버팩 — Express 는 데코레이터가 아니라 `app.get("/x", …)` 로 라우트를 선언하고, async 판정 방식은 선언하지 않는다.
EXPRESS_PACK = (
    'ROLE = "server"\n'
    'ROUTE_PATTERN = r"""\\bapp\\.(?:get|post|put|delete|patch)\\(\\s*["\']([^"\']+)"""\n'
)
FLASK_PACK = (
    'ROLE = "server"\n'
    'ROUTE_PATTERN = r"""@\\w+\\.route\\(\\s*["\']([^"\']+)"""\n'
)
ROUTE_PY = ('from fastapi import APIRouter\nrouter = APIRouter()\n\n'
            '@router.get("/api/orders")\ndef orders() -> list:\n    return []\n')


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class ProjectPackMixin(TemporaryRootTestCase):
    """임시 루트의 `profiles/framework/<이름>.py` 를 커널 팩보다 먼저 찾게 한다."""

    def setUp(self) -> None:
        super().setUp()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(framework, "ROOT", self.root))

    def write_pack(self, name: str, body: str) -> None:
        _write(self.root / framework.PROJECT_DIR / f"{name}.py", body)


class LoaderTests(ProjectPackMixin):
    def test_reference_packs_declare_the_previous_kernel_behaviour(self) -> None:
        server, ui = framework.load_one("fastapi"), framework.load_one("react")
        self.assertEqual((server["ROLE"], server["ASYNC_HANDLER"], server["ERROR_STATUS_KWARG"]),
                         ("server", "python_ast", "status_code"))
        self.assertEqual((ui["ROLE"], ui["UI_EXT"], ui["ESLINT_PARSER"]),
                         ("ui", ("*.tsx", "*.ts"), "@typescript-eslint/parser"))
        self.assertEqual(framework.load(("fastapi", "react")), {"server": server, "ui": ui})
        self.assertEqual(framework.load(()), {"server": None, "ui": None})

    def test_project_pack_wins_and_fills_defaults(self) -> None:
        self.write_pack("express", EXPRESS_PACK)
        pack = framework.load_one("express")
        self.assertEqual((pack["NAME"], pack["ASYNC_HANDLER"], pack["ERROR_STATUS_KWARG"], pack["STREAM_RETURNS"]),
                         ("express", None, None, ()))
        self.write_pack("vue", 'ROLE = "ui"\nUI_EXT = ("*.vue", "*.ts")\nESLINT_PARSER = "vue-eslint-parser"\n')
        self.assertEqual(framework.load_one("vue")["ESLINT_INSTALL"], "npm i -D eslint vue-eslint-parser")

    def test_two_packs_for_one_role_is_an_error(self) -> None:
        self.write_pack("flask", FLASK_PACK)
        with self.assertRaises(ValueError) as caught:
            framework.load(("fastapi", "flask"))
        self.assertIn("role server chosen twice", str(caught.exception))

    def test_bad_declarations_are_errors_not_defaults(self) -> None:
        cases = {
            "norole": 'ROUTE_PATTERN = "x"\n',
            "badrole": 'ROLE = "cli"\n',
            "nogroup": 'ROLE = "server"\nROUTE_PATTERN = r"app\\.get"\n',
            "badasync": 'ROLE = "server"\nROUTE_PATTERN = r"(x)"\nASYNC_HANDLER = "regex"\n',
            "noparser": 'ROLE = "ui"\nUI_EXT = ("*.vue",)\n',
            "noext": 'ROLE = "ui"\nESLINT_PARSER = "p"\n',
            "badreq": 'ROLE = "server"\nROUTE_PATTERN = r"(x)"\nREQUIRES = ({"name": "node"},)\n',
        }
        for name, body in cases.items():
            self.write_pack(name, body)
            with self.subTest(name=name), self.assertRaises(ValueError):
                framework.load_one(name)
        with self.assertRaises(ValueError):
            framework.load(("no-such-framework",))


class ProfileTests(ProjectPackMixin):
    def load_profile(self, source: str) -> object:
        _write(self.root / profile.PROFILE_FILE, source)
        spec = importlib.util.spec_from_file_location("framework_profile", context.ROOT / "kernel/profile.py")
        module = importlib.util.module_from_spec(spec)   # type: ignore[arg-type]  # 커널 경로라 spec 은 항상 있다
        with patch.object(context, "ROOT", self.root):
            spec.loader.exec_module(module)   # type: ignore[union-attr]
        return module

    def test_declared_packs_drive_ui_ext_default(self) -> None:
        loaded = self.load_profile('PROFILE_SCHEMA = 1\nFRAMEWORK = ("fastapi", "react")\n')
        self.assertEqual(loaded.PROFILE_ERRORS, [])
        self.assertEqual((loaded.SERVER["NAME"], loaded.UI["NAME"], loaded.UI_EXT), ("fastapi", "react", ("*.tsx", "*.ts")))
        explicit = self.load_profile('PROFILE_SCHEMA = 1\nFRAMEWORK = ("react",)\nUI_EXT = ("*.vue",)\n')
        self.assertEqual(explicit.UI_EXT, ("*.vue",))

    def test_unselected_frameworks_have_no_react_defaults(self) -> None:
        loaded = self.load_profile("PROFILE_SCHEMA = 1\n")
        self.assertEqual((loaded.PROFILE_ERRORS, loaded.FRAMEWORK, loaded.SERVER, loaded.UI, loaded.UI_EXT),
                         ([], (), None, None, ()))

    def test_role_clash_unknown_pack_and_wrong_shape_are_profile_errors(self) -> None:
        self.write_pack("flask", FLASK_PACK)
        for source, fragment in (('FRAMEWORK = ("fastapi", "flask")\n', "role server chosen twice"),
                                 ('FRAMEWORK = ("no-such-framework",)\n', "not found"),
                                 ('FRAMEWORK = "fastapi"\n', "must be a tuple")):
            with self.subTest(source=source):
                loaded = self.load_profile("PROFILE_SCHEMA = 1\n" + source)
                self.assertTrue(any(fragment in error for error in loaded.PROFILE_ERRORS), loaded.PROFILE_ERRORS)


class RunnerTests(ProjectPackMixin):
    """web_layered 프로젝트 하나를 임시 루트에 두고 러너 섹션을 직접 만든다."""

    def setUp(self) -> None:
        super().setUp()
        self.route = _write(self.root / "web/routes/orders.py", ROUTE_PY)
        self.ui = _write(self.root / "frontend/src/App.tsx", "export const App = () => null;\n")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for module in (context, runner):
            stack.enter_context(patch.object(module, "ROOT", self.root))
        stack.enter_context(patch.object(profile, "NOT_APPLICABLE", {}))
        stack.enter_context(patch.object(profile, "CHECK_PATHS", {
            "routes": "web/routes", "ui": "frontend/src", "ui_admin": None, "ui_tokens": None, "tests": None, "schema": None}))
        stack.enter_context(patch.object(profile, "SYMBOLS", {"ssl_bypass": None, "error_response": "JSONResponse"}))

    def sections(self, files: list[Path], ui_files: list[Path]) -> dict[str, tuple[str, str] | None]:
        return {slug: skip for slug, _title, _found, skip in runner._kernel_sections(files, ui_files)}

    def test_undeclared_packs_skip_web_and_ui_gates_with_reason(self) -> None:
        with patch.object(profile, "SERVER", None), patch.object(profile, "UI", None):
            skips = self.sections([self.route], [self.ui])
        for slug in ("orphan_api", "web_async", "routes_error"):
            self.assertEqual(skips[slug], ("SKIP", runner.NO_SERVER_PACK), slug)
        for slug in linters.UI_SLUGS:
            self.assertEqual(skips[slug], ("SKIP", runner.NO_UI_PACK), slug)

    def test_express_pack_recognises_app_get_routes(self) -> None:
        self.write_pack("express", EXPRESS_PACK)
        route = _write(self.root / "web/routes/x.js", 'app.get("/api/x/:id", (req, res) => res.json([]));\n')
        stranger = _write(self.root / "frontend/src/Other.tsx", "export const url = '/api/other';\n")
        consumer = _write(self.root / "frontend/src/List.tsx", "export const url = `/api/x/${id}`;\n")
        with patch.object(profile, "SERVER", framework.load_one("express")):
            found = orphan_api.check_orphan_api([route], [stranger])
            self.assertEqual(len(found), 1, found)
            self.assertTrue(found[0].startswith("web/routes/x.js:1: `/api/x/:id`"), found[0])
            self.assertEqual(orphan_api.check_orphan_api([route], [stranger, consumer]), [])

    def test_pack_without_async_handler_is_not_applicable(self) -> None:
        self.write_pack("express", EXPRESS_PACK)
        with patch.object(profile, "SERVER", framework.load_one("express")), patch.object(profile, "UI", None):
            skips = self.sections([], [self.ui])
        self.assertEqual(skips["web_async"], ("N/A", "express: does not apply to this framework"))
        self.assertEqual(skips["routes_error"], ("N/A", "express: does not apply to this framework"))

    def test_fastapi_pack_runs_the_python_judgement(self) -> None:
        bad = _write(self.root / "web/routes/lazy.py", "async def lazy() -> int:\n    return 1\n")
        with patch.object(profile, "SERVER", framework.load_one("fastapi")), patch.object(profile, "UI", None):
            found = {slug: found for slug, _title, found, _skip in runner._kernel_sections([self.route, bad], [])}
        self.assertEqual(found["web_async"], ["web/routes/lazy.py:1: async def 'lazy' has no await — make it a plain def"])


class PackCheckTests(unittest.TestCase):
    def test_fastapi_route_recognition_is_first_class(self) -> None:
        verdicts = pack_check.assess_framework(framework.load_one("fastapi"))
        self.assertEqual([(grade, slug) for grade, slug, _reason in verdicts], [("verified", "orphan_api")])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(pack_check.main(["fastapi"]), 0)
        self.assertIn("[VERIFIED] orphan_api", out.getvalue())

    def test_route_examples_that_do_not_match_are_unverified(self) -> None:
        pack = dict(framework.load_one("fastapi"))
        pack["FIXTURES"] = {"orphan_api": {"route": "def plain(): ...\n", "consumer": "x", "stranger": "y"}}
        self.assertEqual(pack_check.assess_framework(pack)[0][:2], ("unverified", "orphan_api"))
        pack["FIXTURES"] = {"orphan_api": {"route": '@app.get("/api/a")\n', "consumer": "'/api/a'", "stranger": "'/api/a'"}}
        self.assertEqual(pack_check.assess_framework(pack)[0], ("unverified", "orphan_api", "stranger example counted as a consumer"))
        pack["FIXTURES"] = {}
        self.assertEqual(pack_check.assess_framework(pack), [("unverified", "orphan_api", "no example")])

    def test_react_examples_without_eslint_are_unverified_not_passed(self) -> None:
        with patch.object(linters, "ui_npm_dir", return_value=None):
            verdicts = pack_check.assess_framework(framework.load_one("react"))
        self.assertEqual([slug for _grade, slug, _reason in verdicts], list(linters.UI_SLUGS))
        self.assertEqual({(grade, reason) for grade, _slug, reason in verdicts},
                         {("unverified", "eslint not installed — npm i -D eslint @typescript-eslint/parser typescript")})

    @unittest.skipUnless(linters.ui_eslint_bin(UILINT), "tests/fixtures/uilint 에 eslint 가 없다")
    def test_react_examples_are_first_class_when_eslint_is_installed(self) -> None:
        with patch.object(linters, "ui_npm_dir", return_value=UILINT):
            verdicts = pack_check.assess_framework(framework.load_one("react"))
        self.assertEqual({grade for grade, _slug, _reason in verdicts}, {"verified"}, verdicts)
        self.assertEqual(list(UILINT.glob("harness_pack_check_*")), [])

    def test_unknown_name_is_exit_2(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pack_check.main(["no-such-pack"]), 2)

    def test_ui_file_globs(self) -> None:
        self.assertEqual(linters.ui_file_globs(("*.tsx", "src/**/*.vue")), ["**/*.tsx", "src/**/*.vue"])


if __name__ == "__main__":
    unittest.main()
