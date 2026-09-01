from pathlib import Path
import html
import re
import time
import unicodedata
import xml.etree.ElementTree as ET

import requests
import yaml

# ============================================================

# CONFIGURATION

# ============================================================

ORCID_ID = "0000-0002-7470-177X"

ORCID_API = "https://pub.orcid.org/v3.0"
ORCID_WORKS_URL = f"{ORCID_API}/{ORCID_ID}/works"

PUBMED_ESEARCH_URL = (
"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

CROSSREF_URL = "https://api.crossref.org/works/"
CROSSREF_SEARCH_URL = "https://api.crossref.org/works"

SCOPUS_SEARCH_URL = (
"https://api.elsevier.com/content/search/scopus"
)

OUTPUT = (
Path(**file**).resolve().parent.parent
/ "_data"
/ "publications.yml"
)

# Scopus API key must be stored as a GitHub Actions secret:

#

# SCOPUS_API_KEY

#

# The script also works without it. In that case Scopus is

# simply skipped.

SCOPUS_API_KEY = None

HEADERS = {
"Accept": "application/json",
"User-Agent": (
"VanharaLab.github.io "
"(https://github.com/VanharaLab/VanharaLab.github.io)"
),
}

SCOPUS_HEADERS = {
"Accept": "application/json",
"User-Agent": HEADERS["User-Agent"],
}

PAGE_SIZE = 100

PUBMED_DELAY = 0.4
CROSSREF_DELAY = 0.2
SCOPUS_DELAY = 0.3

MAX_RETRIES = 5

# ============================================================

# HTTP

# ============================================================

def get_request(url, *, params=None, headers=None):
"""
GET request with retry handling.

```
API failures are retried several times.
The caller decides whether a final failure should
stop processing.
"""

request_headers = headers or HEADERS

last_exception = None

for attempt in range(MAX_RETRIES):
    try:
        response = requests.get(
            url,
            params=params,
            headers=request_headers,
            timeout=60,
        )

        if response.status_code == 429:
            wait = 2 ** attempt

            print(
                f"HTTP 429 received. "
                f"Waiting {wait} seconds..."
            )

            time.sleep(wait)
            continue

        response.raise_for_status()

        return response

    except requests.RequestException as exc:
        last_exception = exc

        if attempt == MAX_RETRIES - 1:
            break

        wait = 2 ** attempt

        print(
            f"Request failed: {exc}. "
            f"Retrying in {wait} seconds..."
        )

        time.sleep(wait)

if last_exception:
    raise last_exception

raise RuntimeError("Request failed after retries")
```

# ============================================================

# TEXT CLEANING

# ============================================================

def clean_text(value):
"""
Remove HTML/XML artifacts and normalize whitespace.
"""

```
if value is None:
    return ""

value = str(value)

value = html.unescape(value)

value = value.replace(
    "\\n",
    " ",
)

value = re.sub(
    r"<[^>]+>",
    "",
    value,
)

value = re.sub(
    r"\s+",
    " ",
    value,
)

return value.strip()
```

def clean_doi(doi):
"""
Normalize DOI.
"""

```
doi = clean_text(doi)

doi = re.sub(
    r"^https?://doi\.org/",
    "",
    doi,
    flags=re.IGNORECASE,
)

doi = re.sub(
    r"^https?://dx\.doi\.org/",
    "",
    doi,
    flags=re.IGNORECASE,
)

doi = re.sub(
    r"^doi:\s*",
    "",
    doi,
    flags=re.IGNORECASE,
)

doi = doi.strip()

doi = doi.rstrip(
    ".,;:"
)

return doi
```

def clean_pmid(pmid):
"""
Normalize PMID.
"""

```
pmid = clean_text(pmid)

match = re.search(
    r"\b\d+\b",
    pmid,
)

if match:
    return match.group(0)

return ""
```

# ============================================================

# TITLE NORMALIZATION

# ============================================================

def normalize_title(title):
"""
Normalize title for comparison.

```
Diacritics are removed so that Czech/European titles
can still be compared reliably between databases.
"""

title = clean_text(title)

title = unicodedata.normalize(
    "NFKD",
    title,
)

title = "".join(
    character
    for character in title
    if not unicodedata.combining(character)
)

title = title.lower()

title = re.sub(
    r"[^a-z0-9]+",
    " ",
    title,
)

return re.sub(
    r"\s+",
    " ",
    title,
).strip()
```

def title_similarity(a, b):
"""
Token-based Jaccard similarity.
"""

```
if not a or not b:
    return 0.0

a_tokens = set(
    a.split()
)

b_tokens = set(
    b.split()
)

if not a_tokens or not b_tokens:
    return 0.0

intersection = len(
    a_tokens & b_tokens
)

union = len(
    a_tokens | b_tokens
)

return intersection / union
```

# ============================================================

# ORCID

# ============================================================

def get_orcid_works():
"""
Download all work summaries from ORCID.
"""

```
print()
print("=" * 60)
print("Fetching publications from ORCID")
print("=" * 60)

all_groups = []

start = 0

while True:
    params = {
        "start": start,
        "rows": PAGE_SIZE,
    }

    print(
        f"ORCID request: start={start}, rows={PAGE_SIZE}"
    )

    try:
        response = get_request(
            ORCID_WORKS_URL,
            params=params,
            headers=HEADERS,
        )

        data = response.json()

    except Exception as exc:
        print(
            f"WARNING: ORCID request failed: {exc}"
        )
        break

    groups = data.get(
        "group",
        [],
    )

    if not groups:
        break

    all_groups.extend(groups)

    print(
        f"  Received {len(groups)} records"
    )

    if len(groups) < PAGE_SIZE:
        break

    start += PAGE_SIZE

print(
    f"ORCID groups found: {len(all_groups)}"
)

return all_groups
```

def get_work_title(work):
return clean_text(
work.get(
"title",
{},
)
.get(
"title",
{},
)
.get(
"value",
"",
)
)

def get_work_year(work):
publication_date = work.get(
"publication-date"
)

```
if not publication_date:
    return ""

year = (
    publication_date
    .get(
        "year",
        {},
    )
    .get(
        "value",
        "",
    )
)

return clean_text(year)
```

def get_work_journal(work):
journal = work.get(
"journal-title"
)

```
if not journal:
    return ""

return clean_text(
    journal.get(
        "value",
        "",
    )
)
```

def get_external_id(work, wanted_type):
"""
Get an external identifier from ORCID.
"""

```
external_ids = (
    work.get(
        "external-ids",
        {},
    )
    .get(
        "external-id",
        [],
    )
)

for external_id in external_ids:
    id_type = clean_text(
        external_id.get(
            "external-id-type",
            "",
        )
    ).lower()

    if id_type == wanted_type.lower():
        value = clean_text(
            external_id.get(
                "external-id-value",
                "",
            )
        )

        return value

return ""
```

def get_doi(work):
return clean_doi(
get_external_id(
work,
"doi",
)
)

def get_pmid(work):
return clean_pmid(
get_external_id(
work,
"pmid",
)
)

def get_orcid_authors(work):
"""
Extract authors/contributors from ORCID.
"""

```
authors = []

contributors = (
    work.get(
        "contributors",
        {},
    )
    .get(
        "contributor",
        [],
    )
)

for contributor in contributors:
    credit_name = clean_text(
        contributor.get(
            "credit-name",
            {},
        )
        .get(
            "value",
            "",
        )
    )

    if credit_name:
        authors.append(
            credit_name
        )
        continue

    contributor_name = clean_text(
        contributor.get(
            "contributor-name",
            {},
        )
        .get(
            "value",
            "",
        )
    )

    if contributor_name:
        authors.append(
            contributor_name
        )

return ", ".join(authors)
```

def get_orcid_work_detail(summary):
"""
Fetch full ORCID work record.
"""

```
put_code = summary.get(
    "put-code"
)

if not put_code:
    return {}

url = (
    f"{ORCID_API}/{ORCID_ID}"
    f"/work/{put_code}"
)

try:
    response = get_request(
        url,
        headers=HEADERS,
    )

    return response.json()

except Exception as exc:
    print(
        f"  WARNING: Could not fetch ORCID "
        f"work {put_code}: {exc}"
    )

    return {}
```

# ============================================================

# PUBMED

# ============================================================

def get_pmid_from_doi(doi):
"""
Find PMID from DOI.
"""

```
if not doi:
    return ""

params = {
    "db": "pubmed",
    "term": f'"{doi}"[doi]',
    "retmode": "json",
    "retmax": 1,
}

time.sleep(PUBMED_DELAY)

try:
    response = get_request(
        PUBMED_ESEARCH_URL,
        params=params,
    )

    data = response.json()

    ids = (
        data.get(
            "esearchresult",
            {},
        )
        .get(
            "idlist",
            [],
        )
    )

    if ids:
        return clean_pmid(
            ids[0]
        )

except Exception as exc:
    print(
        f"  WARNING: PubMed DOI lookup failed: {exc}"
    )

return ""
```

def get_pmid_from_title(title):
"""
Find PMID using title.
"""

```
if not title:
    return ""

params = {
    "db": "pubmed",
    "term": f'"{title}"[Title]',
    "retmode": "json",
    "retmax": 5,
}

time.sleep(PUBMED_DELAY)

try:
    response = get_request(
        PUBMED_ESEARCH_URL,
        params=params,
    )

    data = response.json()

    ids = (
        data.get(
            "esearchresult",
            {},
        )
        .get(
            "idlist",
            [],
        )
    )

    if ids:
        return clean_pmid(
            ids[0]
        )

except Exception as exc:
    print(
        f"  WARNING: PubMed title lookup failed: {exc}"
    )

return ""
```

def get_pubmed_metadata(pmid):
"""
Retrieve complete metadata from PubMed.
"""

```
if not pmid:
    return {}

params = {
    "db": "pubmed",
    "id": pmid,
    "retmode": "xml",
}

time.sleep(PUBMED_DELAY)

try:
    response = get_request(
        PUBMED_EFETCH_URL,
        params=params,
    )
except Exception as exc:
    print(
        f"  WARNING: PubMed request failed: {exc}"
    )
    return {}

try:
    root = ET.fromstring(
        response.text
    )
except ET.ParseError as exc:
    print(
        f"  WARNING: Could not parse PubMed XML "
        f"for PMID {pmid}: {exc}"
    )
    return {}

article = root.find(
    ".//PubmedArticle"
)

if article is None:
    return {}

art = article.find(
    ".//Article"
)

if art is None:
    return {}

# --------------------------------------------------------
# TITLE
# --------------------------------------------------------

title_element = art.find(
    "ArticleTitle"
)

title = ""

if title_element is not None:
    title = "".join(
        title_element.itertext()
    )

    title = clean_text(title)

# --------------------------------------------------------
# JOURNAL
# --------------------------------------------------------

journal = clean_text(
    art.findtext(
        ".//Journal/Title",
        default="",
    )
)

# --------------------------------------------------------
# YEAR
# --------------------------------------------------------

year = clean_text(
    art.findtext(
        ".//PubDate/Year",
        default="",
    )
)

if not year:
    medline_date = clean_text(
        art.findtext(
            ".//PubDate/MedlineDate",
            default="",
        )
    )

    match = re.search(
        r"\b(19|20)\d{2}\b",
        medline_date,
    )

    if match:
        year = match.group(0)

# --------------------------------------------------------
# VOLUME
# --------------------------------------------------------

volume = clean_text(
    art.findtext(
        ".//JournalIssue/Volume",
        default="",
    )
)

# --------------------------------------------------------
# ISSUE
# --------------------------------------------------------

issue = clean_text(
    art.findtext(
        ".//JournalIssue/Issue",
        default="",
    )
)

# --------------------------------------------------------
# PAGES
# --------------------------------------------------------

pages = clean_text(
    art.findtext(
        ".//Pagination/MedlinePgn",
        default="",
    )
)

# --------------------------------------------------------
# AUTHORS
# --------------------------------------------------------

authors = []

for author in art.findall(
    ".//AuthorList/Author"
):
    lastname = clean_text(
        author.findtext(
            "LastName",
            default="",
        )
    )

    initials = clean_text(
        author.findtext(
            "Initials",
            default="",
        )
    )

    collective = clean_text(
        author.findtext(
            "CollectiveName",
            default="",
        )
    )

    if lastname:
        if initials:
            authors.append(
                f"{lastname} {initials}"
            )
        else:
            authors.append(
                lastname
            )

    elif collective:
        authors.append(
            collective
        )

# --------------------------------------------------------
# DOI
# --------------------------------------------------------

doi = ""

for article_id in article.findall(
    ".//ArticleId"
):
    if (
        article_id.attrib.get(
            "IdType",
            "",
        ).lower()
        == "doi"
    ):
        doi = clean_doi(
            article_id.text or ""
        )
        break

# --------------------------------------------------------
# PMID
# --------------------------------------------------------

pubmed_id = clean_pmid(
    article.findtext(
        ".//PMID",
        default=pmid,
    )
)

return {
    "title": title,
    "authors": ", ".join(authors),
    "journal": journal,
    "year": year,
    "volume": volume,
    "issue": issue,
    "pages": pages,
    "doi": doi,
    "pmid": pubmed_id,
}
```

# ============================================================

# CROSSREF

# ============================================================

def get_crossref_metadata(doi):
"""
Retrieve metadata from Crossref using DOI.
"""

```
if not doi:
    return {}

url = (
    CROSSREF_URL
    + requests.utils.quote(
        doi,
        safe="",
    )
)

time.sleep(CROSSREF_DELAY)

try:
    response = get_request(
        url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
        },
    )

    return response.json().get(
        "message",
        {},
    )

except Exception as exc:
    print(
        f"  WARNING: Crossref failed for {doi}: {exc}"
    )

    return {}
```

def get_crossref_metadata_by_title(title):
"""
Search Crossref by title.
"""

```
if not title:
    return {}

params = {
    "query.title": title,
    "rows": 5,
}

time.sleep(CROSSREF_DELAY)

try:
    response = get_request(
        CROSSREF_SEARCH_URL,
        params=params,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
        },
    )

    items = (
        response.json()
        .get(
            "message",
            {},
        )
        .get(
            "items",
            [],
        )
    )

    if not items:
        return {}

    normalized_target = normalize_title(
        title
    )

    best_item = None
    best_score = 0.0

    for item in items:
        item_titles = item.get(
            "title",
            [],
        )

        if not item_titles:
            continue

        candidate = normalize_title(
            item_titles[0]
        )

        score = title_similarity(
            normalized_target,
            candidate,
        )

        if score > best_score:
            best_score = score
            best_item = item

    if best_item and best_score >= 0.85:
        return best_item

except Exception as exc:
    print(
        f"  WARNING: Crossref title search failed: {exc}"
    )

return {}
```

def format_crossref_authors(metadata):
"""
Format Crossref authors as:
Surname AB, Surname CD
"""

```
authors = []

for author in metadata.get(
    "author",
    [],
):
    family = clean_text(
        author.get(
            "family",
            "",
        )
    )

    given = clean_text(
        author.get(
            "given",
            "",
        )
    )

    if not family:
        continue

    initials = ""

    for part in re.split(
        r"[\s\-]+",
        given,
    ):
        if part:
            initials += part[0].upper()

    if initials:
        authors.append(
            f"{family} {initials}"
        )
    else:
        authors.append(
            family
        )

return ", ".join(authors)
```

def get_crossref_year(metadata):
"""
Extract publication year from Crossref.
"""

```
for key in (
    "published-print",
    "published-online",
    "published",
    "issued",
):
    date_parts = (
        metadata.get(
            key,
            {},
        )
        .get(
            "date-parts",
            [],
        )
    )

    if date_parts and date_parts[0]:
        return str(
            date_parts[0][0]
        )

return ""
```

# ============================================================

# SCOPUS

# ============================================================

def get_scopus_api_key():
"""
Read Scopus API key from environment.

```
The key should be configured in GitHub Actions as:

    SCOPUS_API_KEY
"""

import os

return os.environ.get(
    "SCOPUS_API_KEY",
    "",
).strip()
```

def get_scopus_metadata_by_query(query):
"""
Search Scopus.

```
Returns the best matching Scopus result.

This function intentionally does not raise errors.
Scopus is a fallback source only.
"""

api_key = (
    SCOPUS_API_KEY
    or get_scopus_api_key()
)

if not api_key:
    print(
        "  Scopus: API key not configured, skipping."
    )
    return {}

params = {
    "query": query,
    "count": 5,
    "start": 0,
    "view": "COMPLETE",
}

headers = {
    **SCOPUS_HEADERS,
    "X-ELS-APIKey": api_key,
}

time.sleep(SCOPUS_DELAY)

try:
    response = get_request(
        SCOPUS_SEARCH_URL,
        params=params,
        headers=headers,
    )

    data = response.json()

except Exception as exc:
    print(
        f"  WARNING: Scopus request failed: {exc}"
    )
    return {}

entries = (
    data.get(
        "search-results",
        {},
    )
    .get(
        "entry",
        [],
    )
)

if not entries:
    return {}

return entries[0]
```

def get_scopus_metadata_by_doi(doi):
"""
Search Scopus by DOI.
"""

```
if not doi:
    return {}

query = f'DOI("{doi}")'

return get_scopus_metadata_by_query(
    query
)
```

def get_scopus_metadata_by_title(title):
"""
Search Scopus by publication title.
"""

```
if not title:
    return {}

escaped_title = (
    title
    .replace(
        '"',
        " ",
    )
    .strip()
)

query = f'TITLE("{escaped_title}")'

return get_scopus_metadata_by_query(
    query
)
```

def format_scopus_authors(metadata):
"""
Extract Scopus author list.

```
Scopus responses can contain authors either as an
author array or as dc:creator.
"""

authors = []

author_entries = metadata.get(
    "author",
    [],
)

if isinstance(
    author_entries,
    dict,
):
    author_entries = [
        author_entries
    ]

for author in author_entries:
    if not isinstance(
        author,
        dict,
    ):
        continue

    surname = clean_text(
        author.get(
            "surname",
            "",
        )
    )

    given_name = clean_text(
        author.get(
            "given-name",
            "",
        )
    )

    initials = clean_text(
        author.get(
            "initials",
            "",
        )
    )

    if surname:
        if initials:
            authors.append(
                f"{surname} {initials}"
            )
        elif given_name:
            generated_initials = ""

            for part in re.split(
                r"[\s\-]+",
                given_name,
            ):
                if part:
                    generated_initials += (
                        part[0].upper()
                    )

            if generated_initials:
                authors.append(
                    f"{surname} "
                    f"{generated_initials}"
                )
            else:
                authors.append(
                    surname
                )
        else:
            authors.append(
                surname
            )

if authors:
    return ", ".join(authors)

creator = clean_text(
    metadata.get(
        "dc:creator",
        "",
    )
)

return creator
```

def get_scopus_metadata(doi="", title=""):
"""
Get Scopus metadata.

```
DOI is preferred. Title search is the fallback.
"""

if doi:
    print(
        "  Searching Scopus by DOI..."
    )

    result = get_scopus_metadata_by_doi(
        doi
    )

    if result:
        print(
            "  Scopus DOI match: OK"
        )
        return result

if title:
    print(
        "  Searching Scopus by title..."
    )

    result = get_scopus_metadata_by_title(
        title
    )

    if result:
        target = normalize_title(
            title
        )

        candidate = normalize_title(
            result.get(
                "dc:title",
                "",
            )
        )

        score = title_similarity(
            target,
            candidate,
        )

        if score >= 0.80:
            print(
                f"  Scopus title match: OK "
                f"(score={score:.2f})"
            )
            return result

        print(
            f"  WARNING: Scopus title match too weak "
            f"(score={score:.2f})"
        )

return {}
```

def get_scopus_year(metadata):
"""
Extract publication year from Scopus.
"""

```
cover_date = clean_text(
    metadata.get(
        "prism:coverDate",
        "",
    )
)

match = re.search(
    r"\b(19|20)\d{2}\b",
    cover_date,
)

if match:
    return match.group(0)

return ""
```

def format_scopus_metadata(metadata):
"""
Convert Scopus result into our internal metadata format.
"""

```
if not metadata:
    return {}

title = clean_text(
    metadata.get(
        "dc:title",
        "",
    )
)

authors = format_scopus_authors(
    metadata
)

journal = clean_text(
    metadata.get(
        "prism:publicationName",
        "",
    )
)

year = get_scopus_year(
    metadata
)

volume = clean_text(
    metadata.get(
        "prism:volume",
        "",
    )
)

issue = clean_text(
    metadata.get(
        "prism:issueIdentifier",
        "",
    )
)

pages = clean_text(
    metadata.get(
        "prism:pageRange",
        "",
    )
)

doi = clean_doi(
    metadata.get(
        "prism:doi",
        "",
    )
)

identifier = clean_text(
    metadata.get(
        "dc:identifier",
        "",
    )
)

scopus_id = ""

match = re.search(
    r"SCOPUS_ID:(\d+)",
    identifier,
    flags=re.IGNORECASE,
)

if match:
    scopus_id = match.group(1)

return {
    "title": title,
    "authors": authors,
    "journal": journal,
    "year": year,
    "volume": volume,
    "issue": issue,
    "pages": pages,
    "doi": doi,
    "scopus_id": scopus_id,
}
```

# ============================================================

# MERGING

# ============================================================

def first_non_empty(*values):
"""
Return the first non-empty value.
"""

```
for value in values:
    if value is None:
        continue

    value = clean_text(value)

    if value:
        return value

return ""
```

def merge_publication(
orcid_data,
pubmed_data,
scopus_data,
crossref_data,
):
"""
Merge metadata using the following priority:

```
    ORCID
      ↓
    PubMed
      ↓
    Scopus
      ↓
    Crossref

This priority is applied independently to each field.
"""

crossref_title = ""

if crossref_data.get("title"):
    crossref_title = clean_text(
        crossref_data.get(
            "title",
            [""] ,
        )[0]
    )

crossref_journal = ""

if crossref_data.get(
    "container-title"
):
    crossref_journal = clean_text(
        crossref_data.get(
            "container-title",
            [""] ,
        )[0]
    )

title = first_non_empty(
    orcid_data.get("title"),
    pubmed_data.get("title"),
    scopus_data.get("title"),
    crossref_title,
)

year = first_non_empty(
    orcid_data.get("year"),
    pubmed_data.get("year"),
    scopus_data.get("year"),
    get_crossref_year(
        crossref_data
    ),
)

journal = first_non_empty(
    orcid_data.get("journal"),
    pubmed_data.get("journal"),
    scopus_data.get("journal"),
    crossref_journal,
)

authors = first_non_empty(
    orcid_data.get("authors"),
    pubmed_data.get("authors"),
    scopus_data.get("authors"),
    format_crossref_authors(
        crossref_data
    ),
)

volume = first_non_empty(
    orcid_data.get("volume"),
    pubmed_data.get("volume"),
    scopus_data.get("volume"),
    crossref_data.get("volume"),
)

issue = first_non_empty(
    orcid_data.get("issue"),
    pubmed_data.get("issue"),
    scopus_data.get("issue"),
    crossref_data.get("issue"),
)

pages = first_non_empty(
    orcid_data.get("pages"),
    pubmed_data.get("pages"),
    scopus_data.get("pages"),
    crossref_data.get("page"),
    crossref_data.get("article-number"),
)

doi = clean_doi(
    first_non_empty(
        orcid_data.get("doi"),
        pubmed_data.get("doi"),
        scopus_data.get("doi"),
        crossref_data.get("DOI"),
    )
)

pmid = clean_pmid(
    first_non_empty(
        orcid_data.get("pmid"),
        pubmed_data.get("pmid"),
    )
)

scopus_id = first_non_empty(
    scopus_data.get("scopus_id"),
)

return {
    "year": clean_text(year),
    "title": clean_text(title),
    "authors": clean_text(authors),
    "journal": clean_text(journal),
    "volume": clean_text(volume),
    "issue": clean_text(issue),
    "pages": clean_text(pages),
    "doi": clean_doi(doi),
    "pmid": clean_pmid(pmid),
    "scopus_id": clean_text(scopus_id),
}
```

# ============================================================

# SOURCE COMPLETENESS

# ============================================================

def publication_has_missing_data(publication):
"""
Determine whether important metadata is missing.
"""

```
important_fields = (
    "authors",
    "journal",
    "year",
    "doi",
)

for field in important_fields:
    if not publication.get(field):
        return True

return False
```

def missing_fields(publication):
"""
Return names of missing metadata fields.
"""

```
fields = (
    "title",
    "authors",
    "journal",
    "year",
    "volume",
    "issue",
    "pages",
    "doi",
    "pmid",
)

return [
    field
    for field in fields
    if not publication.get(field)
]
```

# ============================================================

# MAIN

# ============================================================

def main():
print()
print("=" * 60)
print("VanharaLab publication updater")
print("=" * 60)

```
groups = get_orcid_works()

if not groups:
    print(
        "WARNING: ORCID returned no publications."
    )
    print(
        "The script will finish without exit code 1."
    )
    return 0

publications = []

print()
print("=" * 60)
print("Processing publications")
print("=" * 60)

for index, group in enumerate(
    groups,
    start=1,
):
    summaries = group.get(
        "work-summary",
        [],
    )

    if not summaries:
        continue

    summary = summaries[0]

    summary_title = get_work_title(
        summary
    )

    print()
    print(
        f"[{index}/{len(groups)}] "
        f"{summary_title or 'Untitled'}"
    )

    # ----------------------------------------------------
    # ORCID FULL RECORD
    # ----------------------------------------------------

    work = get_orcid_work_detail(
        summary
    )

    if not work:
        print(
            "  ORCID detail: FAILED"
        )

        work = summary

    else:
        print(
            "  ORCID detail: OK"
        )

    # ----------------------------------------------------
    # ORCID DATA
    # ----------------------------------------------------

    title = get_work_title(
        work
    )

    year = get_work_year(
        work
    )

    journal = get_work_journal(
        work
    )

    doi = get_doi(
        work
    )

    pmid = get_pmid(
        work
    )

    authors = get_orcid_authors(
        work
    )

    orcid_data = {
        "title": title,
        "year": year,
        "journal": journal,
        "doi": doi,
        "pmid": pmid,
        "authors": authors,
    }

    print(
        "  ORCID authors: "
        f"{'FOUND' if authors else 'MISSING'}"
    )

    print(
        "  ORCID DOI: "
        f"{doi or '-'}"
    )

    print(
        "  ORCID PMID: "
        f"{pmid or '-'}"
    )

    # ----------------------------------------------------
    # PMID LOOKUP
    # ----------------------------------------------------

    if not pmid:
        if doi:
            print(
                "  Looking up PMID from DOI..."
            )

            pmid = get_pmid_from_doi(
                doi
            )

        if not pmid and title:
            print(
                "  Looking up PMID from title..."
            )

            pmid = get_pmid_from_title(
                title
            )

        if pmid:
            print(
                f"  Found PMID: {pmid}"
            )

            orcid_data["pmid"] = pmid

    # ----------------------------------------------------
    # PUBMED
    # ----------------------------------------------------

    pubmed_data = {}

    if pmid:
        print(
            "  Fetching PubMed metadata..."
        )

        pubmed_data = get_pubmed_metadata(
            pmid
        )

        if pubmed_data:
            print(
                "  PubMed metadata: OK"
            )

    # ----------------------------------------------------
    # SCOPUS
    # ----------------------------------------------------

    scopus_data = {}

    # Scopus is queried when:
    #
    # 1. authors are missing
    # 2. important metadata is missing
    # 3. DOI is missing
    #
    # This avoids unnecessary Scopus calls for already
    # complete records.

    preliminary_publication = {
        "title": first_non_empty(
            orcid_data.get("title"),
            pubmed_data.get("title"),
        ),
        "authors": first_non_empty(
            orcid_data.get("authors"),
            pubmed_data.get("authors"),
        ),
        "journal": first_non_empty(
            orcid_data.get("journal"),
            pubmed_data.get("journal"),
        ),
        "year": first_non_empty(
            orcid_data.get("year"),
            pubmed_data.get("year"),
        ),
        "volume": first_non_empty(
            pubmed_data.get("volume"),
        ),
        "issue": first_non_empty(
            pubmed_data.get("issue"),
        ),
        "pages": first_non_empty(
            pubmed_data.get("pages"),
        ),
        "doi": first_non_empty(
            orcid_data.get("doi"),
            pubmed_data.get("doi"),
        ),
        "pmid": first_non_empty(
            orcid_data.get("pmid"),
            pubmed_data.get("pmid"),
        ),
    }

    if publication_has_missing_data(
        preliminary_publication
    ):
        scopus_metadata = get_scopus_metadata(
            doi=doi,
            title=title,
        )

        if scopus_metadata:
            scopus_data = format_scopus_metadata(
                scopus_metadata
            )

    # ----------------------------------------------------
    # CROSSREF
    # ----------------------------------------------------

    crossref_data = {}

    # Crossref is used whenever some metadata is still
    # missing after ORCID + PubMed + Scopus.

    preliminary_after_scopus = {
        "title": first_non_empty(
            orcid_data.get("title"),
            pubmed_data.get("title"),
            scopus_data.get("title"),
        ),
        "authors": first_non_empty(
            orcid_data.get("authors"),
            pubmed_data.get("authors"),
            scopus_data.get("authors"),
        ),
        "journal": first_non_empty(
            orcid_data.get("journal"),
            pubmed_data.get("journal"),
            scopus_data.get("journal"),
        ),
        "year": first_non_empty(
            orcid_data.get("year"),
            pubmed_data.get("year"),
            scopus_data.get("year"),
        ),
        "volume": first_non_empty(
            pubmed_data.get("volume"),
            scopus_data.get("volume"),
        ),
        "issue": first_non_empty(
            pubmed_data.get("issue"),
            scopus_data.get("issue"),
        ),
        "pages": first_non_empty(
            pubmed_data.get("pages"),
            scopus_data.get("pages"),
        ),
        "doi": first_non_empty(
            orcid_data.get("doi"),
            pubmed_data.get("doi"),
            scopus_data.get("doi"),
        ),
    }

    if publication_has_missing_data(
        preliminary_after_scopus
    ):
        if doi:
            print(
                "  Fetching Crossref metadata..."
            )

            crossref_data = (
                get_crossref_metadata(
                    doi
                )
            )

            if crossref_data:
                print(
                    "  Crossref metadata: OK"
                )

        elif title:
            print(
                "  Searching Crossref by title..."
            )

            crossref_data = (
                get_crossref_metadata_by_title(
                    title
                )
            )

            if crossref_data:
                print(
                    "  Crossref title match: OK"
                )

    # ----------------------------------------------------
    # MERGE
    # ----------------------------------------------------

    publication = merge_publication(
        orcid_data,
        pubmed_data,
        scopus_data,
        crossref_data,
    )

    # ----------------------------------------------------
    # SOURCE REPORT
    # ----------------------------------------------------

    print(
        "  Final authors: "
        f"{publication['authors'] or 'MISSING'}"
    )

    print(
        "  Final journal: "
        f"{publication['journal'] or 'MISSING'}"
    )

    print(
        "  Final year: "
        f"{publication['year'] or 'MISSING'}"
    )

    print(
        "  Final DOI: "
        f"{publication['doi'] or '-'}"
    )

    print(
        "  Final PMID: "
        f"{publication['pmid'] or '-'}"
    )

    print(
        "  Final Scopus ID: "
        f"{publication['scopus_id'] or '-'}"
    )

    missing = missing_fields(
        publication
    )

    if missing:
        print(
            "  Remaining missing fields: "
            + ", ".join(missing)
        )
    else:
        print(
            "  Metadata: COMPLETE"
        )

    publications.append(
        publication
    )

# ========================================================
# REMOVE DUPLICATES
# ========================================================

unique = {}

for publication in publications:
    doi = clean_doi(
        publication.get(
            "doi",
            "",
        )
    )

    pmid = clean_pmid(
        publication.get(
            "pmid",
            "",
        )
    )

    scopus_id = clean_text(
        publication.get(
            "scopus_id",
            "",
        )
    )

    title = publication.get(
        "title",
        "",
    )

    if doi:
        key = (
            "doi:"
            + doi.lower()
        )

    elif pmid:
        key = (
            "pmid:"
            + pmid
        )

    elif scopus_id:
        key = (
            "scopus:"
            + scopus_id
        )

    else:
        normalized = normalize_title(
            title
        )

        if normalized:
            key = (
                "title:"
                + normalized
            )
        else:
            key = (
                "unknown:"
                + str(
                    len(unique)
                )
            )

    unique[key] = publication

publications = list(
    unique.values()
)

# ========================================================
# SORT
# ========================================================

def year_sort_key(publication):
    year = publication.get(
        "year",
        "",
    )

    match = re.search(
        r"\b(19|20)\d{2}\b",
        year,
    )

    if match:
        return int(
            match.group(0)
        )

    return 0

publications.sort(
    key=year_sort_key,
    reverse=True,
)

# ========================================================
# VALIDATION
# ========================================================

print()
print("=" * 60)
print("Validation")
print("=" * 60)

print(
    f"ORCID works found:       {len(groups)}"
)

print(
    f"Publications generated:  {len(publications)}"
)

missing_titles = [
    publication
    for publication in publications
    if not publication.get("title")
]

missing_authors = [
    publication
    for publication in publications
    if not publication.get("authors")
]

incomplete = [
    publication
    for publication in publications
    if missing_fields(publication)
]

if missing_titles:
    print(
        f"WARNING: {len(missing_titles)} "
        f"publications have no title."
    )

if missing_authors:
    print(
        f"WARNING: {len(missing_authors)} "
        f"publications have no authors."
    )

    for publication in missing_authors:
        print(
            "  - "
            + (
                publication.get(
                    "title"
                )
                or "Untitled"
            )
        )

print(
    f"Incomplete publications: {len(incomplete)}"
)

# Missing metadata is deliberately a WARNING only.
#
# The script does NOT call:
#
#     raise SystemExit(1)
#
# and therefore incomplete metadata does not make
# GitHub Actions fail.

# ========================================================
# SAVE YAML
# ========================================================

OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

try:
    with open(
        OUTPUT,
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            publications,
            file,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

except Exception as exc:
    print(
        f"WARNING: Could not save YAML: {exc}"
    )

    # Do not fail GitHub Actions because of metadata
    # processing. Return success explicitly.
    return 0

# ========================================================
# FINAL REPORT
# ========================================================

complete_count = (
    len(publications)
    - len(incomplete)
)

print()
print("=" * 60)
print("DONE")
print("=" * 60)

print(
    f"Updated publications:   {len(publications)}"
)

print(
    f"Complete publications:  {complete_count}"
)

print(
    f"Incomplete publications:{len(incomplete)}"
)

print(
    f"Saved to: {OUTPUT}"
)

print()
print(
    "Publication update finished successfully."
)

return 0
```

# ============================================================

# ENTRY POINT

# ============================================================

if **name** == "**main**":
try:
exit_code = main()
except Exception as exc:
print()
print("=" * 60)
print("WARNING")
print("=" * 60)
print(
"Unexpected error occurred:"
)
print(
f"{type(exc).**name**}: {exc}"
)
print()
print(
"The script intentionally exits with code 0 "
"so that missing external metadata does not "
"fail GitHub Actions."
)

```
    exit_code = 0

raise SystemExit(exit_code)
```
