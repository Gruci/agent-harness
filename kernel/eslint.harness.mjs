// kernel/eslint.harness.mjs — 화면 게이트 6종(검사 10·17·18·19·20·42)의 판정 정본.
//
// 러너(kernel/linters.py)가 npm 프로젝트(ui 레이어의 첫 세그먼트)를 cwd 로
//   eslint -c <이 파일> --no-config-lookup --format json <대상>
// 을 부른다. 규칙은 전부 인라인 플러그인이다 — 외부 규칙 패키지 없이 파서만 프로젝트 것을 쓴다.
// 어느 파서인지와 어느 확장자를 볼지는 화면 프레임워크팩(kernel/framework.py)이 선언하고, 러너가 환경변수
// HARNESS_UI_PARSER · HARNESS_UI_PARSER_OPTIONS · HARNESS_UI_FILES 로 넘긴다. 규칙 본문은 스크립트 AST 기준이라
// 파서를 바꿔도 그대로 성립한다(Vue SFC 는 vue-eslint-parser 가 스크립트 블록 AST 를 넘긴다).
// 러너는 메시지 앞의 `[slug]` 로 결과를 섹션에 나눈다. 예외 표시 주석(any-ok · px-ok · web-ok)은
// 정규식 방식을 쓰던 때와 같다. 면제 목록은 환경변수 HARNESS_UI_ALLOW(slug → cwd 기준 glob)로, 토큰 정본 안내 문구는
// HARNESS_UI_TOKENS 로 받는다.
//
// `no-restricted-syntax` 를 블록마다 쓰면 나중 블록이 앞 블록을 덮어써 면제 목록이 섞인다. 그래서 slug 마다 규칙 id 를 따로 둔다.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(path.join(process.cwd(), "package.json"));

const parserName = process.env.HARNESS_UI_PARSER;
if (!parserName) {
  throw new Error("HARNESS_UI_PARSER missing — the runner (kernel/linters.py) passes the UI framework pack's ESLINT_PARSER");
}
const parser = require(parserName);
const parserOptions = JSON.parse(process.env.HARNESS_UI_PARSER_OPTIONS || "{}");
const FILES = JSON.parse(process.env.HARNESS_UI_FILES || "[]");
if (!FILES.length) {
  throw new Error("HARNESS_UI_FILES missing — the runner (kernel/linters.py) passes the UI framework pack's UI_EXT");
}

const allow = JSON.parse(process.env.HARNESS_UI_ALLOW || "{}");
const tokensNote = process.env.HARNESS_UI_TOKENS || "the token file or a CSS variable";

const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const RGB_HSL = /\brgba?\s*\(|\bhsla?\s*\(/;
const FIXED_WIDTH = /(?<![-\w])width\s*:\s*['"]?\d{3,}px/;
const PX_VALUE = /^\d{3,}px$/;
const VW = /\b100vw\b/;
const BROWSER_GLOBALS = new Set(["localStorage", "sessionStorage", "document", "window"]);

/** 같은 줄 주석에 `<token>` 이 있으면 면제 — 기존 관례(`// any-ok: 사유`)를 그대로 잇는다. */
function okOnLine(context, node, token) {
  const line = node.loc.start.line;
  return context.sourceCode.getAllComments()
    .some((c) => c.loc.start.line === line && c.value.includes(token));
}

function stringValue(node) {
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "TemplateElement") return node.value.raw;
  return null;
}

const rules = {
  "ts-any": {
    meta: { type: "problem" },
    create(context) {
      return {
        TSAnyKeyword(node) {
          if (okOnLine(context, node, "any-ok")) return;
          context.report({ node, message: "[ts_any] TS any → concrete type (if unavoidable: `// any-ok: reason`)" });
        },
      };
    },
  },
  "raw-fetch": {
    meta: { type: "problem" },
    create(context) {
      return {
        "CallExpression[callee.name='fetch']"(node) {
          context.report({ node, message: "[raw_fetch] fetch() outside the shared wrapper" });
        },
        "Identifier[name='axios']"(node) {
          context.report({ node, message: "[raw_fetch] axios outside the shared wrapper" });
        },
      };
    },
  },
  "hex-literal": {
    meta: { type: "problem" },
    create(context) {
      const check = (node) => {
        const text = stringValue(node);
        if (text === null) return;
        for (const m of text.matchAll(HEX)) {
          context.report({ node, message: `[hex_literal] hex literal ${m[0]} — use ${tokensNote}` });
        }
        if (RGB_HSL.test(text)) {
          context.report({ node, message: `[hex_literal] rgb()/hsl() color literal — use ${tokensNote}` });
        }
      };
      return { Literal: check, TemplateElement: check };
    },
  },
  "fixed-width": {
    meta: { type: "problem" },
    create(context) {
      const report = (node, message) => {
        if (okOnLine(context, node, "px-ok")) return;
        context.report({ node, message });
      };
      const checkText = (node) => {
        const text = stringValue(node);
        if (text === null) return;
        if (FIXED_WIDTH.test(text)) report(node, "[responsive] fixed px width — use max-width, %, minmax or clamp (if unavoidable: `// px-ok: reason`)");
        if (VW.test(text)) report(node, "[responsive] 100vw overflows horizontally by the vertical scrollbar width — use 100%");
      };
      return {
        Literal: checkText,
        TemplateElement: checkText,
        Property(node) {
          const key = node.key.name || node.key.value;
          const value = stringValue(node.value);
          if (key === "width" && value !== null && PX_VALUE.test(value)) {
            report(node, "[responsive] fixed px width — use max-width, %, minmax or clamp (if unavoidable: `// px-ok: reason`)");
          }
        },
      };
    },
  },
  "browser-api": {
    meta: { type: "problem" },
    create(context) {
      return {
        Program(node) {
          const scope = context.sourceCode.getScope(node);
          for (const ref of scope.through) {
            const name = ref.identifier.name;
            if (!BROWSER_GLOBALS.has(name)) continue;
            if (okOnLine(context, ref.identifier, "web-ok")) continue;
            context.report({ node: ref.identifier, message: `[browser_api] direct browser API call ${name} — go through the wrapper (if unavoidable: \`// web-ok: reason\`)` });
          }
        },
      };
    },
  },
  "hash-nav": {
    meta: { type: "problem" },
    create(context) {
      let hashchange = false, replaceState = false, hashEvent = false;
      return {
        "CallExpression[callee.object.name='history'][callee.property.name='pushState']"(node) {
          context.report({ node, message: "[hash_nav] history.pushState — assign `location.hash = …` to add a navigation step. pushState fires no hashchange event, so the restore listener never runs" });
        },
        "CallExpression[callee.property.name='addEventListener'][arguments.0.value='popstate']"(node) {
          context.report({ node, message: "[hash_nav] popstate listener — restore hash state with a single hashchange listener. popstate does not fire when the hash is assigned within the same document" });
        },
        "Literal[value='hashchange']"() { hashchange = true; },
        "MemberExpression[property.name='replaceState']"() { replaceState = true; },
        "Identifier[name='HashChangeEvent']"() { hashEvent = true; },
        "Program:exit"(node) {
          if (hashchange && replaceState && !hashEvent) {
            context.report({ node, loc: { line: 1, column: 0 }, message: "[hash_nav] restoring on hashchange while fixing the hash with replaceState — replaceState fires no event, so wake the listener with `window.dispatchEvent(new HashChangeEvent('hashchange'))`" });
          }
        },
      };
    },
  },
};

const block = (slug, rule) => ({ files: FILES, ignores: allow[slug] || [], rules: { [`harness/${rule}`]: "error" } });

export default [
  {
    files: FILES,
    languageOptions: { parser, parserOptions },
    plugins: { harness: { rules } },
  },
  block("ts_any", "ts-any"),
  block("raw_fetch", "raw-fetch"),
  block("hex_literal", "hex-literal"),
  block("responsive", "fixed-width"),
  block("browser_api", "browser-api"),
  block("hash_nav", "hash-nav"),
];
