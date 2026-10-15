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
// HARNESS_UI_TOKENS 로 받는다. 확장자별 파서(HARNESS_UI_PARSERS, glob → 패키지 — Svelte 팩의 `.ts` 를 TS 파서로)는 그 glob 에만
// 파서를 바꾸는 블록이 된다. 파서 패키지는 HARNESS_UI_MODULES(실행 파일이 든 node_modules 의 npm 폴더, worktree 면 공유
// 체크아웃의 것)에서, 없으면 cwd 에서 찾는다.
//
// `no-restricted-syntax` 를 블록마다 쓰면 나중 블록이 앞 블록을 덮어써 면제 목록이 섞인다. 그래서 slug 마다 규칙 id 를 따로 둔다.
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(path.join(process.env.HARNESS_UI_MODULES || process.cwd(), "package.json"));

const parserName = process.env.HARNESS_UI_PARSER;
if (!parserName) {
  throw new Error("HARNESS_UI_PARSER missing — the runner (kernel/linters.py) passes the UI framework pack's ESLINT_PARSER");
}
const parser = require(parserName);
const parserOptions = JSON.parse(process.env.HARNESS_UI_PARSER_OPTIONS || "{}");
const extraParsers = Object.entries(JSON.parse(process.env.HARNESS_UI_PARSERS || "{}"));
const FILES = JSON.parse(process.env.HARNESS_UI_FILES || "[]");
if (!FILES.length) {
  throw new Error("HARNESS_UI_FILES missing — the runner (kernel/linters.py) passes the UI framework pack's UI_EXT");
}

const allow = JSON.parse(process.env.HARNESS_UI_ALLOW || "{}");
const tokensNote = process.env.HARNESS_UI_TOKENS || "the token file or a CSS variable";

const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const RGB_HSL = /\brgba?\s*\(|\bhsla?\s*\(/;
const FIXED_WIDTH = /(?<![-\w])(?:min-)?width\s*:\s*['"]?\d{3,}px/;
const TAILWIND_WIDTH = /(?<![-\w])(?:min-)?w-\[\d{3,}px\]/;
const PX_VALUE = /^\d{3,}px$/;
const VW = /\b100vw\b/;
const WIDTH_KEYS = new Set(["width", "minWidth", "min-width"]);
const STYLE_OWNER = /style|css|^sx$/i;
const COLOR_KEYS = new Set(["color", "background", "backgroundColor", "borderColor", "fill", "stroke"]);
// CSS 이름 색 148개. 목록으로 대조한다 — `color="primary"` 같은 컴포넌트 라이브러리의 의미 이름은 색 리터럴이 아니다.
const NAMED_COLORS = new Set((
  "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood " +
  "cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray " +
  "darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
  "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue " +
  "firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew " +
  "hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
  "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray " +
  "lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue " +
  "mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred " +
  "midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
  "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple " +
  "rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue " +
  "slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white " +
  "whitesmoke yellow yellowgreen").split(" "));
const FETCH_HOSTS = new Set(["window", "globalThis", "self"]);
const BROWSER_GLOBALS = new Set(["localStorage", "sessionStorage", "document", "window"]);
const FIXED_MESSAGE = "[responsive] fixed px width — use max-width, %, minmax or clamp (if unavoidable: `// px-ok: reason`)";

/** 같은 줄 주석에 `<token>` 이 있으면 면제 — 기존 관례(`// any-ok: 사유`)를 그대로 잇는다. */
function okOnLine(context, node, token) {
  const line = node.loc.start.line;
  return context.sourceCode.getAllComments()
    .some((c) => c.loc.start.line === line && c.value.includes(token));
}

function stringValue(node) {
  if (!node) return null;
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "TemplateElement") return node.value.raw;
  return null;
}

/** 이 속성이 든 객체가 스타일 객체인가 — `style={{…}}`·`sx={{…}}`, 또는 이름에 style·css 가 든 변수·키의 값. */
function inStyleObject(node) {
  const owner = node.parent && node.parent.parent;
  if (!owner) return false;
  if (owner.type === "JSXExpressionContainer") {
    return owner.parent.type === "JSXAttribute" && STYLE_OWNER.test(String(owner.parent.name.name));
  }
  const name = owner.type === "VariableDeclarator" ? owner.id.name
    : owner.type === "Property" ? owner.key.name || owner.key.value : "";
  return STYLE_OWNER.test(String(name || ""));
}

// 스타일 맥락인가 — 가장 가까운 JSX 속성·변수 선언·함수 선언의 이름, 또는 거쳐 가는 스타일 함수 호출(styled·css·
// StyleSheet.create)·속성 키의 이름에 style·css 가 들었거나 sx 다. 다른 함수 호출(`useMemo`·`items.map`)은 건너 올라간다.
// `{ label: 'Paid', color: 'green' }` 같은 조회표는 스타일이 아니다.
const STYLE_NAME = /style|css|^sx$/i;
function inStyle(context, node) {
  for (let p = node.parent; p; p = p.parent) {
    if (p.type === "JSXAttribute") return STYLE_NAME.test(p.name.name ?? "");
    if (p.type === "CallExpression" && STYLE_NAME.test(context.sourceCode.getText(p.callee))) return true;
    if (p.type === "VariableDeclarator" || p.type === "FunctionDeclaration") return STYLE_NAME.test(p.id?.name ?? "");
    if (p.type === "Property" && STYLE_NAME.test(String(p.key.name ?? p.key.value ?? ""))) return true;
  }
  return false;
}

/** 스타일 객체 속성(`{ width: 480 }`)과 JSX 속성(`<path fill="red" />`)의 (이름, 값 노드). 둘 다 아니면 null. */
function keyValue(node) {
  if (node.type === "Property") return [node.key.name || node.key.value, node.value];
  if (node.type === "JSXAttribute" && node.name.type === "JSXIdentifier") {
    const value = node.value && node.value.type === "JSXExpressionContainer" ? node.value.expression : node.value;
    return [node.name.name, value];
  }
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
        "CallExpression[callee.type='MemberExpression'][callee.property.name='fetch']"(node) {
          if (!FETCH_HOSTS.has(node.callee.object.name)) return;
          context.report({ node, message: `[raw_fetch] ${node.callee.object.name}.fetch() outside the shared wrapper` });
        },
        "NewExpression[callee.name='XMLHttpRequest']"(node) {
          context.report({ node, message: "[raw_fetch] XMLHttpRequest outside the shared wrapper" });
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
      // 색 속성의 이름 색(`color: 'red'`). transparent·currentColor·inherit 같은 키워드는 목록에 없어 통과한다.
      const named = (node) => {
        const pair = keyValue(node);
        const text = pair && COLOR_KEYS.has(pair[0]) ? stringValue(pair[1]) : null;
        if (text === null || !NAMED_COLORS.has(text.toLowerCase()) || !inStyle(context, node)) return;
        context.report({ node, message: `[hex_literal] named color ${text} — use ${tokensNote}` });
      };
      // 이름 색은 스타일 객체 속성만 본다 — JSX 속성(`<Badge color="green">`)과 조회표 값은 컴포넌트 라이브러리의 의미 이름이다
      return { Literal: check, TemplateElement: check, Property: named };
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
        if (FIXED_WIDTH.test(text) || TAILWIND_WIDTH.test(text)) report(node, FIXED_MESSAGE);
        if (VW.test(text)) report(node, "[responsive] 100vw overflows horizontally by the vertical scrollbar width — use 100%");
      };
      return {
        Literal: checkText,
        TemplateElement: checkText,
        // 폭 속성 — 문자열 `'480px'`, 그리고 스타일 객체 안에서 React 가 px 로 읽는 숫자 `480`
        Property(node) {
          if (!WIDTH_KEYS.has(node.key.name || node.key.value)) return;
          const value = stringValue(node.value);
          const number = node.value.type === "Literal" && typeof node.value.value === "number" ? node.value.value : null;
          if ((value !== null && PX_VALUE.test(value)) || (number !== null && number >= 100 && inStyleObject(node))) {
            report(node, FIXED_MESSAGE);
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
  ...extraParsers.map(([glob, name]) => ({ files: [glob], languageOptions: { parser: require(name) } })),
  block("ts_any", "ts-any"),
  block("raw_fetch", "raw-fetch"),
  block("hex_literal", "hex-literal"),
  block("responsive", "fixed-width"),
  block("browser_api", "browser-api"),
  block("hash_nav", "hash-nav"),
];
