// kernel/eslint.harness.mjs — 화면 게이트 6종(검사 10·17·18·19·20·42)의 판정 정본.
//
// 러너(kernel/linters.py)가 npm 프로젝트(frontend/)를 cwd 로
//   eslint -c <이 파일> --no-config-lookup --format json <대상>
// 을 부른다. 규칙은 전부 인라인 플러그인이다 — 외부 규칙 패키지 없이 파서(@typescript-eslint/parser)만
// 프로젝트 것을 쓴다. 러너는 메시지 앞의 `[slug]` 로 결과를 섹션에 나눈다. 예외 표시 주석(any-ok · px-ok · web-ok)은
// 정규식 방식을 쓰던 때와 같다. 면제 목록은 환경변수 HARNESS_UI_ALLOW(slug → cwd 기준 glob)로, 토큰 정본 안내 문구는
// HARNESS_UI_TOKENS 로 받는다.
//
// `no-restricted-syntax` 를 블록마다 쓰면 나중 블록이 앞 블록을 덮어써 면제 목록이 섞인다. 그래서 slug 마다 규칙 id 를 따로 둔다.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(path.join(process.cwd(), "package.json"));
const tsParser = require("@typescript-eslint/parser");

const allow = JSON.parse(process.env.HARNESS_UI_ALLOW || "{}");
const tokensNote = process.env.HARNESS_UI_TOKENS || "토큰 정본 또는 CSS 변수";

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
          context.report({ node, message: "[ts_any] TS any → 구체 타입 (불가피하면 `// any-ok: 사유`)" });
        },
      };
    },
  },
  "raw-fetch": {
    meta: { type: "problem" },
    create(context) {
      return {
        "CallExpression[callee.name='fetch']"(node) {
          context.report({ node, message: "[raw_fetch] 공용 래퍼를 거치지 않는 fetch()" });
        },
        "Identifier[name='axios']"(node) {
          context.report({ node, message: "[raw_fetch] 공용 래퍼를 거치지 않는 axios" });
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
          context.report({ node, message: `[hex_literal] hex 리터럴 ${m[0]} — ${tokensNote} 로` });
        }
        if (RGB_HSL.test(text)) {
          context.report({ node, message: `[hex_literal] rgb()·hsl() 색 리터럴 — ${tokensNote} 로` });
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
        if (FIXED_WIDTH.test(text)) report(node, "[responsive] 고정 px 폭 — max-width·%·minmax·clamp 로 (불가피하면 `// px-ok: 사유`)");
        if (VW.test(text)) report(node, "[responsive] 100vw 는 세로 스크롤바 폭만큼 가로로 넘친다 — 100% 로 바꾼다");
      };
      return {
        Literal: checkText,
        TemplateElement: checkText,
        Property(node) {
          const key = node.key.name || node.key.value;
          const value = stringValue(node.value);
          if (key === "width" && value !== null && PX_VALUE.test(value)) {
            report(node, "[responsive] 고정 px 폭 — max-width·%·minmax·clamp 로 (불가피하면 `// px-ok: 사유`)");
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
            context.report({ node: ref.identifier, message: `[browser_api] 브라우저 API 직접 호출 ${name} — 래퍼를 거쳐 호출한다 (불가피하면 \`// web-ok: 사유\`)` });
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
          context.report({ node, message: "[hash_nav] history.pushState — 탐색 깊이를 한 단계 늘리려면 `location.hash = …` 로 대입한다. pushState 는 hashchange 이벤트를 내지 않아 복원 리스너가 실행되지 않는다" });
        },
        "CallExpression[callee.property.name='addEventListener'][arguments.0.value='popstate']"(node) {
          context.report({ node, message: "[hash_nav] popstate 리스너 — 해시 복원은 hashchange 리스너 하나로만 한다. popstate 는 같은 문서 안에서 해시를 대입할 때 발생하지 않는다" });
        },
        "Literal[value='hashchange']"() { hashchange = true; },
        "MemberExpression[property.name='replaceState']"() { replaceState = true; },
        "Identifier[name='HashChangeEvent']"() { hashEvent = true; },
        "Program:exit"(node) {
          if (hashchange && replaceState && !hashEvent) {
            context.report({ node, loc: { line: 1, column: 0 }, message: "[hash_nav] hashchange 로 복원하면서 replaceState 로 해시를 고치고 있다 — replaceState 는 이벤트를 내지 않으므로 `window.dispatchEvent(new HashChangeEvent('hashchange'))` 로 깨운다" });
          }
        },
      };
    },
  },
};

const FILES = ["**/*.ts", "**/*.tsx"];
const block = (slug, rule) => ({ files: FILES, ignores: allow[slug] || [], rules: { [`harness/${rule}`]: "error" } });

export default [
  {
    files: FILES,
    languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true }, sourceType: "module" } },
    plugins: { harness: { rules } },
  },
  block("ts_any", "ts-any"),
  block("raw_fetch", "raw-fetch"),
  block("hex_literal", "hex-literal"),
  block("responsive", "fixed-width"),
  block("browser_api", "browser-api"),
  block("hash_nav", "hash-nav"),
];
