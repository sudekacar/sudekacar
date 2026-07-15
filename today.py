"""
Daily profile updater for sudekacar.
Inspired by Andrew6rant/Andrew6rant — stats + stacks from GitHub projects.
"""
import datetime
import hashlib
import os
import time
from collections import Counter

import requests
from dateutil import relativedelta
from lxml import etree

HEADERS = {"authorization": "token " + os.environ.get("ACCESS_TOKEN", "")}
USER_NAME = os.environ.get("USER_NAME", "sudekacar")
QUERY_COUNT = {
    "user_getter": 0,
    "follower_getter": 0,
    "graph_repos_stars": 0,
    "recursive_loc": 0,
    "loc_query": 0,
    "languages": 0,
}

OWNER_ID = None

# Topics / keywords mapped into stack buckets (from repo metadata)
TOPIC_BUCKETS = {
    "Programming": {
        "python", "typescript", "javascript", "java", "c++", "go", "rust", "sql",
        "nodejs",
    },
    "Frameworks": {
        "nextjs", "react", "streamlit", "tailwindcss", "fastapi", "django",
        "flask", "express", "vue", "context-api", "i18n", "fullstack",
    },
    "AI/ML": {
        "gemini", "rag", "nlp", "llm", "langchain", "openai", "huggingface",
        "machine-learning", "deep-learning", "computer-vision", "ai-safety",
        "benchmark", "jupyter", "rag-ready", "llm-evaluation", "sarcasm-detection",
    },
    "Data": {
        "sqlite", "postgresql", "mongodb", "pandas", "numpy", "scikit-learn",
        "data-science", "data-engineering", "ecommerce", "logistics",
    },
}

# Ignore noisy / vendored languages when building stacks
IGNORE_LANGS = {
    "Perl", "Makefile", "Dockerfile", "Procfile", "Batchfile", "PowerShell",
    "Shell", "Hack", "Rich Text Format",
}

LANG_BUCKETS = {
    "Python": "Programming",
    "TypeScript": "Programming",
    "JavaScript": "Programming",
    "HTML": "Frameworks",
    "CSS": "Frameworks",
    "SCSS": "Frameworks",
    "Jupyter Notebook": "AI/ML",
    "Vue": "Frameworks",
    "Go": "Programming",
    "Rust": "Programming",
    "Java": "Programming",
    "C++": "Programming",
    "SQL": "Data",
}

TOPIC_LABELS = {
    "nextjs": "Next.js",
    "tailwindcss": "Tailwind",
    "react": "React",
    "streamlit": "Streamlit",
    "gemini": "Gemini",
    "rag": "RAG",
    "rag-ready": "RAG",
    "nlp": "NLP",
    "llm": "LLM",
    "llm-evaluation": "LLM Eval",
    "langchain": "LangChain",
    "sqlite": "SQLite",
    "postgresql": "PostgreSQL",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scikit-learn": "Scikit-Learn",
    "data-science": "Data Science",
    "data-engineering": "Data Eng",
    "machine-learning": "ML",
    "jupyter": "Jupyter",
    "typescript": "TypeScript",
    "python": "Python",
    "javascript": "JavaScript",
    "ai-safety": "AI Safety",
    "benchmark": "Benchmarking",
    "fullstack": "Fullstack",
    "context-api": "Context API",
    "ecommerce": "E-commerce",
    "i18n": "i18n",
}


def daily_readme(birthday):
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return "{} {}, {} {}, {} {}{}".format(
        diff.years,
        "year" + format_plural(diff.years),
        diff.months,
        "month" + format_plural(diff.months),
        diff.days,
        "day" + format_plural(diff.days),
        " 🎂" if (diff.months == 0 and diff.days == 0) else "",
    )


def format_plural(unit):
    return "s" if unit != 1 else ""


def simple_request(func_name, query, variables):
    request = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
    )
    if request.status_code == 200:
        return request
    raise Exception(func_name, "failed", request.status_code, request.text, QUERY_COUNT)


def graph_repos_stars(count_type, owner_affiliation, cursor=None):
    query_count("graph_repos_stars")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers { totalCount }
                        }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }"""
    variables = {
        "owner_affiliation": owner_affiliation,
        "login": USER_NAME,
        "cursor": cursor,
    }
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if count_type == "repos":
        return request.json()["data"]["user"]["repositories"]["totalCount"]
    if count_type == "stars":
        return stars_counter(request.json()["data"]["user"]["repositories"]["edges"])


def recursive_loc(
    owner,
    repo_name,
    data,
    cache_comment,
    addition_total=0,
    deletion_total=0,
    my_commits=0,
    cursor=None,
):
    query_count("recursive_loc")
    query = """
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    ... on Commit {
                                        author { user { id } }
                                        deletions
                                        additions
                                    }
                                }
                            }
                            pageInfo { endCursor hasNextPage }
                        }
                    }
                }
            }
        }
    }"""
    variables = {"repo_name": repo_name, "owner": owner, "cursor": cursor}
    request = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
    )
    if request.status_code == 200:
        ref = request.json()["data"]["repository"]["defaultBranchRef"]
        if ref is not None:
            return loc_counter_one_repo(
                owner,
                repo_name,
                data,
                cache_comment,
                ref["target"]["history"],
                addition_total,
                deletion_total,
                my_commits,
            )
        return 0
    force_close_file(data, cache_comment)
    if request.status_code == 403:
        raise Exception("GitHub rate/abuse limit hit while counting LOC")
    raise Exception("recursive_loc failed", request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(
    owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits
):
    for node in history["edges"]:
        if node["node"]["author"]["user"] == OWNER_ID:
            my_commits += 1
            addition_total += node["node"]["additions"]
            deletion_total += node["node"]["deletions"]

    if history["edges"] == [] or not history["pageInfo"]["hasNextPage"]:
        return addition_total, deletion_total, my_commits
    return recursive_loc(
        owner,
        repo_name,
        data,
        cache_comment,
        addition_total,
        deletion_total,
        my_commits,
        history["pageInfo"]["endCursor"],
    )


def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=None):
    if edges is None:
        edges = []
    query_count("loc_query")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            defaultBranchRef {
                                target {
                                    ... on Commit {
                                        history { totalCount }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo { endCursor hasNextPage }
            }
        }
    }"""
    variables = {
        "owner_affiliation": owner_affiliation,
        "login": USER_NAME,
        "cursor": cursor,
    }
    request = simple_request(loc_query.__name__, query, variables)
    page = request.json()["data"]["user"]["repositories"]
    edges = edges + page["edges"]
    if page["pageInfo"]["hasNextPage"]:
        return loc_query(
            owner_affiliation,
            comment_size,
            force_cache,
            page["pageInfo"]["endCursor"],
            edges,
        )
    return cache_builder(edges, comment_size, force_cache)


def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    filename = "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = f.readlines()
    except FileNotFoundError:
        data = []
        if comment_size > 0:
            for _ in range(comment_size):
                data.append("cache comment line\n")
        with open(filename, "w", encoding="utf-8") as f:
            f.writelines(data)

    if len(data) - comment_size != len(edges) or force_cache:
        flush_cache(edges, filename, comment_size)
        with open(filename, "r", encoding="utf-8") as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for index in range(len(edges)):
        repo_hash, commit_count, *_rest = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]["node"]["nameWithOwner"].encode("utf-8")).hexdigest():
            try:
                total = edges[index]["node"]["defaultBranchRef"]["target"]["history"]["totalCount"]
                if int(commit_count) != total:
                    owner, repo_name = edges[index]["node"]["nameWithOwner"].split("/")
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = (
                        f"{repo_hash} {total} {loc[2]} {loc[0]} {loc[1]}\n"
                    )
            except TypeError:
                data[index] = repo_hash + " 0 0 0 0\n"
        with open(filename, "w", encoding="utf-8") as f:
            f.writelines(cache_comment)
            f.writelines(data)
    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, True]


def flush_cache(edges, filename, comment_size):
    with open(filename, "r", encoding="utf-8") as f:
        data = f.readlines()[:comment_size] if comment_size > 0 else []
    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(data)
        for node in edges:
            digest = hashlib.sha256(node["node"]["nameWithOwner"].encode("utf-8")).hexdigest()
            f.write(digest + " 0 0 0 0\n")


def force_close_file(data, cache_comment):
    filename = "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(cache_comment)
        f.writelines(data)


def stars_counter(data):
    return sum(node["node"]["stargazers"]["totalCount"] for node in data)


def commit_counter(comment_size):
    filename = "cache/" + hashlib.sha256(USER_NAME.encode("utf-8")).hexdigest() + ".txt"
    with open(filename, "r", encoding="utf-8") as f:
        data = f.readlines()[comment_size:]
    return sum(int(line.split()[2]) for line in data)


def user_getter(username):
    query_count("user_getter")
    query = """
    query($login: String!){
        user(login: $login) { id createdAt }
    }"""
    request = simple_request(user_getter.__name__, query, {"login": username})
    user = request.json()["data"]["user"]
    return {"id": user["id"]}, user["createdAt"]


def follower_getter(username):
    query_count("follower_getter")
    query = """
    query($login: String!){
        user(login: $login) { followers { totalCount } }
    }"""
    request = simple_request(follower_getter.__name__, query, {"login": username})
    return int(request.json()["data"]["user"]["followers"]["totalCount"])


def fetch_stacks_from_projects():
    """Pull languages + topics from public non-fork repos and build stack lines."""
    query_count("languages")
    buckets = {
        "Programming": Counter(),
        "Frameworks": Counter(),
        "AI/ML": Counter(),
        "Data": Counter(),
    }

    auth_headers = {"Accept": "application/vnd.github+json"}
    if HEADERS.get("authorization", "").strip() not in ("token", "token "):
        auth_headers.update(HEADERS)

    page = 1
    while True:
        resp = requests.get(
            f"https://api.github.com/users/{USER_NAME}/repos",
            params={"per_page": 100, "page": page, "type": "owner", "sort": "updated"},
            headers=auth_headers,
            timeout=30,
        )
        if resp.status_code != 200:
            raise Exception("repos list failed", resp.status_code, resp.text)
        repos = resp.json()
        if not repos:
            break
        for repo in repos:
            if repo.get("fork"):
                continue
            # Prefer primary language heavily
            lang = repo.get("language")
            if lang and lang not in IGNORE_LANGS:
                if lang in LANG_BUCKETS:
                    buckets[LANG_BUCKETS[lang]][lang] += 5
                else:
                    buckets["Programming"][lang] += 2

            for topic in repo.get("topics") or []:
                t = topic.lower()
                if t in {"config", "github-config", "dark-mode"}:
                    continue
                placed = False
                for bucket, keywords in TOPIC_BUCKETS.items():
                    if t in keywords:
                        label = TOPIC_LABELS.get(t, topic.replace("-", " ").title())
                        buckets[bucket][label] += 4
                        placed = True
                        break
                if not placed:
                    # soft match (e.g. rag-ready contains rag)
                    for bucket, keywords in TOPIC_BUCKETS.items():
                        hit = next((k for k in keywords if k in t or t in k), None)
                        if hit:
                            label = TOPIC_LABELS.get(t) or TOPIC_LABELS.get(hit) or topic.replace("-", " ").title()
                            buckets[bucket][label] += 3
                            placed = True
                            break

            # language bytes — only for known/important langs (skip vendored noise)
            lang_resp = requests.get(repo["languages_url"], headers=auth_headers, timeout=30)
            if lang_resp.status_code == 200:
                langs = lang_resp.json()
                total = sum(langs.values()) or 1
                for name, bytes_count in langs.items():
                    if name in IGNORE_LANGS:
                        continue
                    share = bytes_count / total
                    if share < 0.02 and name not in ("TypeScript", "Python", "JavaScript"):
                        continue
                    bucket = LANG_BUCKETS.get(name, "Programming")
                    if name in LANG_BUCKETS or share >= 0.05:
                        buckets[bucket][name] += max(1, int(share * 10))
        page += 1
        if page > 5:
            break

    # Seed with known strengths from your portfolio
    defaults = {
        "Programming": ["Python", "TypeScript", "JavaScript"],
        "Frameworks": ["Next.js", "React", "Streamlit", "Tailwind"],
        "AI/ML": ["Gemini", "RAG", "NLP", "Jupyter"],
        "Data": ["SQLite", "Pandas", "NumPy"],
    }
    for bucket, seeds in defaults.items():
        for item in seeds:
            buckets[bucket][item] += 1

    # Drop presentation langs from Frameworks if real frameworks exist
    for noise in ("HTML", "CSS", "SCSS"):
        if any(k not in ("HTML", "CSS", "SCSS") for k in buckets["Frameworks"]):
            buckets["Frameworks"].pop(noise, None)

    result = {}
    for bucket, counter in buckets.items():
        items = [name for name, _ in counter.most_common(8)]
        # prefer defaults order for stability on sparse data
        ordered = []
        for d in defaults[bucket]:
            if d in items and d not in ordered:
                ordered.append(d)
        for name in items:
            if name not in ordered:
                ordered.append(name)
        result[bucket] = ", ".join(ordered[:5])
    return result


def fetch_language_bytes():
    """Aggregate language byte counts across public non-fork repos."""
    auth_headers = {"Accept": "application/vnd.github+json"}
    if HEADERS.get("authorization", "").strip() not in ("token", "token "):
        auth_headers.update(HEADERS)

    totals = Counter()
    page = 1
    while True:
        resp = requests.get(
            f"https://api.github.com/users/{USER_NAME}/repos",
            params={"per_page": 100, "page": page, "type": "owner"},
            headers=auth_headers,
            timeout=30,
        )
        if resp.status_code != 200:
            break
        repos = resp.json()
        if not repos:
            break
        for repo in repos:
            if repo.get("fork"):
                continue
            lang_resp = requests.get(repo["languages_url"], headers=auth_headers, timeout=30)
            if lang_resp.status_code == 200:
                for name, nbytes in lang_resp.json().items():
                    if name not in IGNORE_LANGS:
                        totals[name] += nbytes
        page += 1
        if page > 5:
            break
    return totals.most_common(8)


LANG_COLORS = {
    "Python": "#3572A5",
    "TypeScript": "#3178C6",
    "JavaScript": "#F7DF1E",
    "Jupyter Notebook": "#DA5B0B",
    "CSS": "#563D7C",
    "HTML": "#E34C26",
    "Go": "#00ADD8",
    "Rust": "#DEA584",
    "Java": "#B07219",
    "C++": "#F34B7D",
    "SQL": "#E38C00",
    "Shell": "#89E051",
}


def _esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_top_languages_svg(filename, lang_data):
    """Render top languages bar chart as a self-hosted SVG."""
    w, h = 420, 200
    if not lang_data:
        lang_data = [("Python", 1), ("TypeScript", 1)]

    max_bytes = max(n for _, n in lang_data) or 1
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="Consolas,Menlo,monospace">',
        f'<rect width="{w}" height="{h}" rx="12" fill="#0C0C14" stroke="#BC3DF2" stroke-width="1.5"/>',
        f'<text x="18" y="28" fill="#FF00EA" font-size="15" font-weight="bold">Top Languages</text>',
        f'<text x="18" y="46" fill="#6B5B7A" font-size="11">from public repos</text>',
    ]

    y = 62
    bar_max = w - 150
    for lang, nbytes in lang_data[:7]:
        pct = nbytes / max_bytes
        bar_w = max(8, int(bar_max * pct))
        color = LANG_COLORS.get(lang, "#C084FC")
        label = lang if len(lang) <= 16 else lang[:14] + "…"
        lines.append(f'<text x="18" y="{y + 12}" fill="#E6E6FA" font-size="12">{_esc(label)}</text>')
        lines.append(
            f'<rect x="130" y="{y}" width="{bar_w}" height="16" rx="4" fill="{color}" opacity="0.9"/>'
        )
        lines.append(f'<text x="{130 + bar_w + 8}" y="{y + 12}" fill="#C084FC" font-size="11">{_esc(f"{pct*100:.1f}%")}</text>')
        y += 22

    lines.append("</svg>")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_github_stats_svg(filename, stats):
    """Render GitHub stats card as a self-hosted SVG."""
    w, h = 460, 195
    items = [
        ("Stars", stats.get("stars", 0), "★"),
        ("Repos", stats.get("repos", 0), "◆"),
        ("Commits", stats.get("commits", 0), "●"),
        ("Followers", stats.get("followers", 0), "♥"),
        ("Lines of Code", stats.get("loc", 0), "▲"),
    ]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="Consolas,Menlo,monospace">',
        f'<rect width="{w}" height="{h}" rx="12" fill="#0C0C14" stroke="#BC3DF2" stroke-width="1.5"/>',
        f'<text x="18" y="30" fill="#FF00EA" font-size="16" font-weight="bold">GitHub Stats</text>',
        f'<text x="18" y="50" fill="#6B5B7A" font-size="11">@{_esc(USER_NAME)}</text>',
    ]

    x, y = 18, 72
    col_w = 140
    for i, (label, value, icon) in enumerate(items):
        col = i % 3
        row = i // 3
        cx = x + col * col_w
        cy = y + row * 58
        val = f"{value:,}" if isinstance(value, int) else str(value)
        lines.append(f'<text x="{cx}" y="{cy}" fill="#C084FC" font-size="14">{icon}</text>')
        lines.append(f'<text x="{cx + 18}" y="{cy}" fill="#E6E6FA" font-size="13" font-weight="bold">{_esc(val)}</text>')
        lines.append(f'<text x="{cx}" y="{cy + 18}" fill="#6B5B7A" font-size="11">{_esc(label)}</text>')

    lines.append("</svg>")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data, stacks):
    tree = etree.parse(filename)
    root = tree.getroot()
    justify_format(root, "age_data", age_data, 22)
    justify_format(root, "commit_data", commit_data, 18)
    justify_format(root, "star_data", star_data, 10)
    justify_format(root, "repo_data", repo_data, 6)
    justify_format(root, "contrib_data", contrib_data)
    justify_format(root, "follower_data", follower_data, 8)
    justify_format(root, "loc_data", loc_data[2], 10)
    justify_format(root, "loc_add", loc_data[0])
    justify_format(root, "loc_del", loc_data[1], 7)

    # stack lines (no heavy justify — just replace text)
    find_and_replace(root, "stack_prog", stacks["Programming"])
    find_and_replace(root, "stack_fw", stacks["Frameworks"])
    find_and_replace(root, "stack_ai", stacks["AI/ML"])
    find_and_replace(root, "stack_data", stacks["Data"])
    tree.write(filename, encoding="utf-8", xml_declaration=True)


def justify_format(root, element_id, new_text, length=0):
    if isinstance(new_text, int):
        new_text = f"{new_text:,}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    if length:
        just_len = max(0, length - len(new_text))
        if just_len <= 2:
            dot_string = {0: "", 1: " ", 2: ". "}[just_len]
        else:
            dot_string = " " + ("." * just_len) + " "
        find_and_replace(root, f"{element_id}_dots", dot_string)


def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def perf_counter(funct, *args):
    start = time.perf_counter()
    result = funct(*args)
    return result, time.perf_counter() - start


def formatter(query_type, difference):
    print("{:<23}".format(" " + query_type + ":"), sep="", end="")
    if difference > 1:
        print("{:>12}".format("%.4f" % difference + " s "))
    else:
        print("{:>12}".format("%.4f" % (difference * 1000) + " ms"))


if __name__ == "__main__":
    print("Calculation times:")
    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, _acc_date = user_data
    formatter("account data", user_time)

    # Prefer BIRTHDAY env (YYYY-MM-DD); fallback = GitHub join date as "GitHub uptime"
    birthday_env = os.environ.get("BIRTHDAY")
    if birthday_env:
        y, m, d = map(int, birthday_env.split("-"))
        birthday = datetime.datetime(y, m, d)
    else:
        birthday = datetime.datetime(2003, 6, 2)  # override via BIRTHDAY secret if needed

    age_data, age_time = perf_counter(daily_readme, birthday)
    formatter("age calculation", age_time)

    stacks, stacks_time = perf_counter(fetch_stacks_from_projects)
    formatter("stacks from repos", stacks_time)
    print("  stacks:", stacks)

    total_loc, loc_time = perf_counter(
        loc_query, ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"], 7
    )
    formatter("LOC", loc_time)

    commit_data, commit_time = perf_counter(commit_counter, 7)
    formatter("commits", commit_time)
    star_data, star_time = perf_counter(graph_repos_stars, "stars", ["OWNER"])
    formatter("stars", star_time)
    repo_data, repo_time = perf_counter(graph_repos_stars, "repos", ["OWNER"])
    formatter("repos", repo_time)
    contrib_data, contrib_time = perf_counter(
        graph_repos_stars, "repos", ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"]
    )
    formatter("contributed", contrib_time)
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)
    formatter("followers", follower_time)

    for index in range(len(total_loc) - 1):
        total_loc[index] = "{:,}".format(total_loc[index])

    for svg in ("dark_mode.svg", "light_mode.svg"):
        svg_overwrite(
            svg,
            age_data,
            commit_data,
            star_data,
            repo_data,
            contrib_data,
            follower_data,
            total_loc[:-1],
            stacks,
        )

    lang_data, lang_time = perf_counter(fetch_language_bytes)
    formatter("language bytes", lang_time)
    write_top_languages_svg("top_languages.svg", lang_data)
    write_github_stats_svg(
        "github_stats.svg",
        {
            "stars": star_data,
            "repos": repo_data,
            "commits": commit_data,
            "followers": follower_data,
            "loc": int(str(total_loc[2]).replace(",", "")) if total_loc else 0,
        },
    )
    print("  wrote top_languages.svg + github_stats.svg")

    print("Total GitHub GraphQL API calls:", sum(QUERY_COUNT.values()))
    for name, count in QUERY_COUNT.items():
        print(f"  {name}: {count}")
