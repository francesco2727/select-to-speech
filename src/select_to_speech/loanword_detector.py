"""Detect English loanwords/tech terms for mixed-language phonemization.

Used to keep the same voice (e.g. Italian if_sara) while switching the
phonemization language to English for individual words, so "Python" or
"GitHub" get the correct English pronunciation even inside Italian text.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Case-insensitive set of English tech words and loanwords that would be
# mispronounced by non-English phonemizers.
_ENGLISH_TECH_WORDS: frozenset[str] = frozenset({
    # --- Programming languages ---
    "python", "java", "javascript", "typescript", "golang", "rust",
    "swift", "kotlin", "ruby", "php", "perl", "scala", "dart",
    "elixir", "haskell", "clojure", "julia", "lua", "groovy",
    "powershell", "bash", "shell", "cobol", "fortran", "assembly",
    "ocaml", "fsharp", "vhdl", "verilog",
    # --- Platforms & tools ---
    "github", "gitlab", "bitbucket", "docker", "kubernetes",
    "terraform", "jenkins", "ansible", "vagrant", "gradle", "maven",
    "webpack", "babel", "eslint", "prettier", "heroku", "netlify",
    "vercel", "firebase", "supabase", "stripe", "npm", "pip", "cargo",
    "homebrew", "chocolatey", "makefile", "cmake", "poetry", "yarn",
    "pnpm", "brew", "kubectl", "helm", "skaffold", "podman",
    # --- OS / distros ---
    "linux", "ubuntu", "debian", "fedora", "centos", "arch",
    "manjaro", "windows", "macos", "freebsd", "openbsd", "gentoo",
    "nixos", "alpine", "kali", "raspbian", "chromeos",
    # --- Frameworks & libraries ---
    "react", "angular", "vue", "node", "express", "django", "flask",
    "fastapi", "pydantic", "spring", "laravel", "rails", "bootstrap",
    "jquery", "redux", "vite", "nuxt", "svelte", "astro", "nextjs",
    "remix", "gatsby", "storybook", "tailwind", "shadcn", "prisma",
    "drizzle", "trpc", "graphene", "celery", "gunicorn", "uvicorn",
    "pytorch", "tensorflow", "keras", "numpy", "pandas", "sklearn",
    "matplotlib", "seaborn", "plotly", "scipy", "jupyter",
    # --- Databases ---
    "mysql", "postgresql", "postgres", "mongodb", "redis",
    "elasticsearch", "cassandra", "sqlite", "dynamodb", "mariadb",
    "cockroachdb", "influxdb", "neo4j", "couchdb", "firestore",
    "planetscale", "neon", "turso", "clickhouse", "snowflake",
    # --- Cloud & DevOps ---
    "aws", "azure", "gcp", "devops", "devsecops", "gitops",
    "serverless", "microservices", "monorepo", "monolith",
    "kubernetes", "openshift", "rancher", "istio", "linkerd",
    "prometheus", "grafana", "datadog", "splunk", "sentry",
    "newrelic", "pagerduty", "cloudwatch", "lightsail", "cloudfront",
    # --- Companies / brands ---
    "google", "microsoft", "amazon", "apple", "netflix", "spotify",
    "slack", "zoom", "discord", "whatsapp", "instagram", "twitter",
    "youtube", "linkedin", "facebook", "meta", "openai", "anthropic",
    "cloudflare", "hashicorp", "jetbrains", "atlassian", "salesforce",
    "hubspot", "shopify", "twilio", "sendgrid", "okta", "datadog",
    "figma", "notion", "airtable", "intercom", "segment", "amplitude",
    "mixpanel", "hotjar", "typeform", "webflow", "framer", "canva",
    "dropbox", "box", "notion", "obsidian", "todoist", "trello",
    "asana", "jira", "confluence", "basecamp", "clickup", "linear",
    # --- AI / ML ---
    "chatgpt", "copilot", "gemini", "claude", "llm", "gpt",
    "transformer", "diffusion", "embedding", "tokenizer", "tokenization",
    "finetuning", "fine-tuning", "pretraining", "prompting",
    "langchain", "llamaindex", "huggingface", "ollama", "mistral",
    "llama", "whisper", "stable", "midjourney", "dall-e",
    # --- Tech jargon (significantly different pronunciation) ---
    "backend", "frontend", "fullstack", "workflow", "feedback",
    "deploy", "deployment", "staging", "pipeline", "endpoint",
    "dashboard", "roadmap", "milestone", "sprint", "backlog",
    "commit", "branch", "merge", "pull", "push", "release",
    "rollback", "debug", "build", "patch", "middleware", "gateway",
    "cluster", "container", "runtime", "widget", "snippet",
    "wrapper", "handler", "token", "payload", "buffer", "proxy",
    "cache", "plugin", "template", "repository", "refactor",
    "refactoring", "linting", "scaffold", "scaffolding",
    "boilerplate", "mock", "stub", "fixture", "hook", "callback",
    "coroutine", "goroutine", "thread", "async", "await", "stream",
    "socket", "webhook", "cron", "daemon", "watchdog", "sandbox",
    "breakpoint", "profiler", "profiling", "benchmark", "benchmarking",
    "canary", "feature flag", "rollout", "hotfix", "bugfix",
    "changelog", "semantic versioning", "semver",
    # --- General anglicisms used across many languages ---
    "file", "byte", "bytes", "bit", "bits", "wifi", "cloud", "browser",
    "mouse", "drive", "email", "chat", "smartphone", "laptop", "tablet",
    "router", "server", "client", "host", "web", "app", "blog",
    "tweet", "post", "like", "share", "story", "reel", "feed",
    "online", "offline", "software", "hardware", "update", "upgrade",
    "download", "upload", "streaming", "podcast", "newsletter",
    "startup", "scaleup", "unicorn", "pitch", "fundraising",
    "crowdfunding", "airdrop", "blockchain", "nft", "token", "wallet",
    "staking", "mining", "defi", "web3", "metaverse",
    "screenshot", "screencast", "screenreader", "screensharing",
    "backup", "restore", "sync", "clone", "fork", "repo",
    "password", "username", "login", "logout", "signup", "checkout",
    "freelance", "remote", "coworking", "standup", "kickoff",
    "brainstorming", "workshop", "webinar", "meetup", "hackathon",
    "community", "open source", "open-source",
    # --- Protocols / formats ---
    "http", "https", "ssh", "ftp", "smtp", "imap", "pop3", "dns",
    "url", "uri", "urn", "api", "rest", "graphql", "grpc", "soap",
    "json", "xml", "yaml", "toml", "csv", "tsv", "pdf", "svg",
    "jwt", "oauth", "saml", "oidc", "ldap", "websocket", "webrtc",
    "quic", "tcp", "udp", "ip", "ipv4", "ipv6", "ssl", "tls",
    "html", "css", "sql", "nosql", "markdown",
    # --- Hardware & acronyms ---
    "cpu", "gpu", "tpu", "ram", "rom", "ssd", "hdd", "nvme",
    "usb", "hdmi", "displayport", "thunderbolt", "bluetooth",
    "nfc", "rfid", "lidar", "iot", "embedded", "firmware",
    "bios", "uefi", "pcie", "ddr", "overclocking", "benchmark",
    # --- Media / entertainment ---
    "streaming", "playlist", "trailer", "reboot", "remake", "spinoff",
    "spin-off", "crossover", "cameo", "biopic", "mockumentary",
    "sitcom", "showrunner", "binge-watching", "binge", "spoiler",
    "cliffhanger", "franchise", "blockbuster", "indie",
    # --- Business / marketing ---
    "marketing", "branding", "rebranding", "storytelling", "content",
    "influencer", "engagement", "reach", "impression", "conversion",
    "funnel", "lead", "churn", "retention", "onboarding", "upselling",
    "cross-selling", "b2b", "b2c", "saas", "paas", "iaas",
    "roi", "kpi", "okr", "nps", "cta", "cro", "seo", "sem", "ppc",
    "backlink", "keyword", "landing page", "split test", "a/b test",
    "growth hacking", "product market fit", "mvp",
    # --- Finance / crypto ---
    "bitcoin", "ethereum", "crypto", "cryptocurrency", "altcoin",
    "exchange", "trading", "hedge fund", "venture capital", "equity",
    "leverage", "short", "long", "yield", "stablecoin", "defi",
    # --- Everyday anglicisms (cross-language) ---
    "ok", "okay", "bye", "sorry", "please", "thank you", "thanks",
    "cool", "wow", "yes", "no", "bye", "hi", "hello", "hey",
    "party", "happy hour", "afterwork", "after-work", "weekend",
    "stress", "feeling", "mood", "vibe", "trend", "hype",
    "vintage", "fashion", "outfit", "look", "style", "brand",
    "sneakers", "hoodie", "t-shirt", "jeans", "leggings",
    "burger", "hot dog", "sandwich", "brunch", "lunch", "snack",
    "smoothie", "cocktail", "shot", "beer", "bar", "club",
    "gym", "fitness", "wellness", "mindfulness", "coach", "coaching",
    "burnout", "detox", "selfie", "avatar", "profile",
})


def _is_english_loanword(word: str) -> bool:
    """Return True if *word* should be phonemized as English."""
    # Curated set (case-insensitive)
    if word.lower() in _ENGLISH_TECH_WORDS:
        return True
    # CamelCase: e.g. GitHub, TypeScript, JavaScript, WebSocket
    if re.match(r'^[A-Z][a-z]+[A-Z][a-zA-Z]*$', word):
        return True
    # All-caps acronym (2+ letters): API, HTTP, CPU, REST
    if re.match(r'^[A-Z]{2,}$', word):
        return True
    return False


def segment_with_loanwords(
    text: str,
    dominant_lang: str,
) -> list[tuple[str, str, Optional[str]]]:
    """Split *text* into (segment, voice_lang, phoneme_lang) tuples.

    - ``voice_lang`` is always ``dominant_lang`` (the same voice is used throughout)
    - ``phoneme_lang`` is ``"en"`` for detected English loanwords, ``None`` otherwise
      (meaning: use the voice's native phonemization)

    If ``dominant_lang`` is already ``"en"``, returns the whole text as a
    single segment with no override — no extra work needed.
    """
    if dominant_lang == "en":
        return [(text, dominant_lang, None)]

    raw: list[tuple[str, str, Optional[str]]] = []
    last_end = 0

    for match in re.finditer(r"\b\w[\w'-]*\b", text):
        word = match.group()
        start, end = match.start(), match.end()

        # Non-word characters (spaces, punctuation) before this word
        if start > last_end:
            raw.append((text[last_end:start], dominant_lang, None))

        phoneme = "en" if _is_english_loanword(word) else None
        raw.append((word, dominant_lang, phoneme))
        last_end = end

    # Trailing non-word characters
    if last_end < len(text):
        raw.append((text[last_end:], dominant_lang, None))

    if not raw:
        return [(text, dominant_lang, None)]

    # Merge consecutive segments that share the same phoneme_lang
    merged: list[list] = [list(raw[0])]
    for seg_text, seg_voice, seg_phoneme in raw[1:]:
        if seg_phoneme == merged[-1][2]:
            merged[-1][0] += seg_text
        else:
            merged.append([seg_text, seg_voice, seg_phoneme])

    result: list[tuple[str, str, Optional[str]]] = [
        (s[0], s[1], s[2]) for s in merged
    ]

    en_segments = [s[0].strip() for s in result if s[2] == "en" and s[0].strip()]
    if en_segments:
        logger.debug(
            "English loanword segments (%d): %s",
            len(en_segments),
            ", ".join(f"'{w}'" for w in en_segments[:8]),
        )

    return result
