"""kernel/langs/java.py — Java 언어팩. 프로젝트는 `profiles/lang/java.py` 로 덮어쓸 수 있다.

타입·미정의 이름은 javac 가, 관용구는 프로젝트의 빌드 도구(Maven·Gradle 의 checkstyle·SpotBugs)가 잡는다. 하네스는
구문 사실만 정규식 분석기(`REGEX`, 설치 0개)로 읽어 언어 무관 게이트와 컴포넌트 의존 검사를 켠다.

모듈 키는 경로(`src/main/java/com/x/Orders.java` → `src.main.java.com.x.Orders`)이고, import 의 패키지 이름은
그 키의 접미로 찾는다(MODULE_RULE dotted). 레포에서 못 찾은 이름은 외부 의존이고, `java.`·`javax.`·`jdk.` 는 표준이다.
"""

from __future__ import annotations

EXT = ("*.java",)
SYNTAX = "java"
ANALYZER = "regex"
MODULE_RULE = "dotted"

# 메서드 머리는 `반환형 이름(`, 생성자는 `대문자 이름(`. 호출문·인터페이스 메서드도 잡히지만 본문 `{` 가 없으면 빠진다.
_MODIFIERS = r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)[ \t]+)*"
REGEX = {
    "functions": (r"^[ \t]*(?:@\w+(?:\([^)\n]*\))?[ \t]+)*" + _MODIFIERS + r"(?:<[^>\n]*>[ \t]+)?"
                  r"(?!(?:return|new|throw|else|case|yield|record|class|interface|enum)\b)"
                  r"[\w$.]+(?:<[^\n(;=]*?>)?(?:\[\])*[ \t]+(?P<name>[A-Za-z_$][\w$]*)[ \t]*\("
                  r"|^[ \t]*(?:(?:public|protected|private)[ \t]+)?(?P<ctor>[A-Z][\w$]*)[ \t]*\("),
    "imports": r"^[ \t]*import[ \t]+(?:static[ \t]+)?(?P<path>[\w$.]+(?:\.\*)?)[ \t]*;",
    "top_symbols": (r"^(?:@\w+[ \t]+)*(?:(?:public|protected|private|abstract|final|sealed|non-sealed|static|strictfp)[ \t]+)*"
                    r"(?:class|interface|enum|record|@interface)[ \t]+(?P<name>[A-Za-z_$][\w$]*)"),
}
STDLIB = ("java.", "javax.", "jdk.")

# 적합성 검사 예제 — closures·type_hints 는 NOT_APPLICABLE 이라 예제가 없다.
FIXTURES = {
    "files": {"src/main/java/com/example/app/db/Reads.java": "package com.example.app.db;\n\npublic class Reads {}\n"},
    "func_limit": {
        "violating": "class A {\n    void run() {\n" + "        int x = 1;\n" * 80 + "    }\n}\n",
        "passing": "class A {\n    void run() {\n        int x = 1;\n    }\n}\n",
    },
    "imports": {
        "path": "src/main/java/com/example/app/orders/Service.java",
        "source": ("package com.example.app.orders;\n\nimport java.util.List;\nimport com.example.app.db.Reads;\n\n"
                   "public class Service {}\n"),
        "expect": ["src.main.java.com.example.app.db.Reads"],
    },
    "top_symbols": {
        "source": "package a;\n\npublic class Thing {\n    public static class Inner {}\n}\n\ninterface Port {}\n",
        "expect": ["Thing", "Port"],
    },
}

PATTERNS = {
    "env_read":    r"\bSystem\.getenv\b",
    # Object 매개변수·필드·지역변수. 제네릭 인자(`List<Object>`)는 컬렉션 관용이라 보지 않는다
    "any_type":    r"[(,]\s*(?:final\s+)?Object\s+\w+\s*[,)]|^\s*(?:(?:private|protected|public|static|final|volatile|transient)\s+)*Object\s+\w+\s*[;=]",
    "any_escape":  "any-ok",
    "closure_escape": "closure-ok",
    "comment":     "//",
    "import_stmt": r"^\s*import\b",
}

NOT_APPLICABLE = {
    "type_hints": "javac enforces types, so none can be missing",
    "closures":   "lambdas and anonymous classes are idiomatic, so banning nested functions is wrong",
    "web_async":  "no async/await keyword (threads and CompletableFuture are a different model)",
    "undefined_const":      "Python-only check — javac rejects undefined names",
    "type_checking_future": "Python-only check — Java has no typing.TYPE_CHECKING",
}

NAMING = {"function": "camel", "keys": "camel"}
OWNED = {
    "http_client": (r"^\s*import\s+(?:java\.net\.http\.|java\.net\.HttpURLConnection\b|okhttp3\.|org\.apache\.(?:http|hc\.client5)\."
                    r"|org\.springframework\.web\.(?:client\.RestTemplate|reactive\.function\.client\.WebClient)\b)"),
    "db_connect": r"\bDriverManager\.getConnection\(",
}

LINTERS: list[dict] = []     # 빌드 도구가 맡는다 — mvn·gradle 의 검사 단계를 프로파일 LINTERS 로 켠다
