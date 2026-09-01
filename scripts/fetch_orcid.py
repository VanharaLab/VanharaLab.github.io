```python
from pathlib import Path
import html
import os
import re
import time
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

SCOPUS_ABSTRACT_URL = (
    "https://api.elsevier.com/content/abstract"
)

SCOPUS_SEARCH_URL = (
    "https://api.elsevier.com/content/search/scopus"
)

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "_data"
    / "publications.yml"
)

# ------------------------------------------------------------
# Scopus API key
#
# GitHub Actions:
#
#   env:
#     SCOPUS_API_KEY: ${{ secrets.SCOPUS_API_KEY }}
#
# Local shell:
#
#   export SCOPUS_API_KEY="your-key"
#
# ------------------------------------------------------------

SCOPUS_API_KEY = os.getenv(
    "SCOPUS_API_KEY",
    "",
).strip()


HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "VanharaLab.github.io "
        "(https://github.com/VanharaLab/VanharaLab.github.io)"
    ),
}

PAGE_SIZE = 100

PUBMED_DELAY = 0.4
CROSSREF_DELAY = 0.2
SCOPUS_DELAY = 0.3

MAX_RETRIES = 5


# ============================================================
# HTTP
# ============================================================

def get_request(
    url,
    *,
    params=None,
    headers=None,
):
    """
    GET request with retry handling.

    Never calls sys.exit().

    Exceptions are raised to the caller, which can decide
    whether the particular data source is optional.
    """

    request_headers = headers or HEADERS

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

            if attempt == MAX_RETRIES - 1:
                raise

            wait = 2 ** attempt

            print(
                f"Request failed: {exc}. "
                f"Retrying in {wait} seconds..."
            )

            time.sleep(wait)

    raise RuntimeError(
        "Request failed after retries"
    )


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(value):
    """
    Remove HTML/XML artifacts and normalize whitespace.
    """

    if value is None:
        return ""

    value = str(value)

    value = html.unescape(value)

    value = re.sub(
        r"<[^>]+>",
        "",
        value,
    )

    value = value.replace(
        "\\n",
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def clean_doi(doi):
    """
    Normalize DOI.
    """

    doi = clean_text(doi)

    doi = re.sub(
        r"^https?://doi\.org/",
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

    return doi.strip()


# ============================================================
# ORCID
# ============================================================

def get_orcid_works():
    """
    Download all work summaries from ORCID.
    """

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

        except Exception as exc:

            print(
                f"ERROR: ORCID request failed: {exc}"
            )

            # Do not terminate with exit code 1.
            return all_groups

        try:

            data = response.json()

        except ValueError as exc:

            print(
                f"ERROR: Invalid ORCID JSON: {exc}"
            )

            return all_groups

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


def get_work_title(work):

    return clean_text(
        work.get("title", {})
        .get("title", {})
        .get("value", "")
    )


def get_work_year(work):

    publication_date = work.get(
        "publication-date"
    )

    if not publication_date:
        return ""

    year = (
        publication_date
        .get("year", {})
        .get("value", "")
    )

    return clean_text(year)


def get_work_journal(work):

    journal = work.get(
        "journal-title"
    )

    if not journal:
        return ""

    return clean_text(
        journal.get("value", "")
    )


def get_external_id(
    work,
    wanted_type,
):
    """
    Get external identifier from ORCID.
    """

    external_ids = (
        work.get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:

        id_type = clean_text(
            external_id.get(
                "external-id-type",
                "",
            )
        ).lower()

        if id_type == wanted_type.lower():

            return clean_text(
                external_id.get(
                    "external-id-value",
                    "",
                )
            )

    return ""


def get_doi(work):

    return clean_doi(
        get_external_id(
            work,
            "doi",
        )
    )


def get_pmid(work):

    return clean_text(
        get_external_id(
            work,
            "pmid",
        )
    )


def get_orcid_authors(work):
    """
    Extract authors/contributors from ORCID.
    """

    authors = []

    contributors = (
        work.get("contributors", {})
        .get("contributor", [])
    )

    for contributor in contributors:

        credit_name = clean_text(
            contributor.get(
                "credit-name",
                {},
            ).get(
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
            ).get(
                "value",
                "",
            )
        )

        if contributor_name:

            authors.append(
                contributor_name
            )

    return ", ".join(authors)


def get_orcid_work_detail(summary):

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
            f"  WARNING: ORCID work "
            f"{put_code} failed: {exc}"
        )

        return {}


# ============================================================
# PUBMED
# ============================================================

def get_pmid_from_doi(doi):

    if not doi:
        return ""

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1,
    }

    time.sleep(PUBMED_DELAY)

    response = get_request(
        PUBMED_ESEARCH_URL,
        params=params,
    )

    data = response.json()

    ids = (
        data.get("esearchresult", {})
        .get("idlist", [])
    )

    if ids:
        return str(ids[0])

    return ""


def get_pmid_from_title(title):

    if not title:
        return ""

    params = {
        "db": "pubmed",
        "term": f'"{title}"[Title]',
        "retmode": "json",
        "retmax": 5,
    }

    time.sleep(PUBMED_DELAY)

    response = get_request(
        PUBMED_ESEARCH_URL,
        params=params,
    )

    data = response.json()

    ids = (
        data.get("esearchresult", {})
        .get("idlist", [])
    )

    if ids:
        return str(ids[0])

    return ""


def get_pubmed_metadata(pmid):

    if not pmid:
        return {}

    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
    }

    time.sleep(PUBMED_DELAY)

    response = get_request(
        PUBMED_EFETCH_URL,
        params=params,
    )

    try:

        root = ET.fromstring(
            response.text
        )

    except ET.ParseError:

        print(
            f"WARNING: Could not parse PubMed XML "
            f"for PMID {pmid}"
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

    pubmed_id = clean_text(
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


# ============================================================
# CROSSREF
# ============================================================

def get_crossref_metadata(doi):

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
            f"WARNING: Crossref failed "
            f"for {doi}: {exc}"
        )

        return {}


def get_crossref_metadata_by_title(title):

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
            .get("message", {})
            .get("items", [])
        )

        if not items:
            return {}

        normalized_target = normalize_title(
            title
        )

        best_item = None
        best_score = 0

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
            f"WARNING: Crossref title search failed: {exc}"
        )

    return {}


def format_crossref_authors(metadata):

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


def get_crossref_year(metadata):

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


# ============================================================
# SCOPUS
# ============================================================

def scopus_available():

    if not SCOPUS_API_KEY:

        print(
            "WARNING: SCOPUS_API_KEY is not set. "
            "Scopus fallback disabled."
        )

        return False

    return True


def get_scopus_headers():

    return {
        "Accept": "application/json",
        "X-ELS-APIKey": SCOPUS_API_KEY,
        "User-Agent": HEADERS["User-Agent"],
    }


def get_scopus_metadata_by_identifier(
    identifier_type,
    identifier,
):
    """
    Retrieve Scopus metadata using:

        doi
        pubmed_id
        scopus_id
        eid
        pii
        pui
    """

    if not scopus_available():
        return {}

    if not identifier:
        return {}

    identifier = clean_text(identifier)

    url = (
        f"{SCOPUS_ABSTRACT_URL}/"
        f"{identifier_type}/"
        f"{requests.utils.quote(identifier, safe='')}"
    )

    time.sleep(SCOPUS_DELAY)

    try:

        response = get_request(
            url,
            headers=get_scopus_headers(),
            params={
                "view": "META",
            },
        )

        data = response.json()

        return data

    except Exception as exc:

        print(
            f"WARNING: Scopus lookup failed "
            f"({identifier_type}={identifier}): {exc}"
        )

        return {}


def get_scopus_search(
    query,
):
    """
    Search Scopus.

    Used as a final fallback when DOI/PMID lookup
    is not possible.
    """

    if not scopus_available():
        return {}

    if not query:
        return {}

    params = {
        "query": query,
        "count": 5,
        "start": 0,
    }

    time.sleep(SCOPUS_DELAY)

    try:

        response = get_request(
            SCOPUS_SEARCH_URL,
            params=params,
            headers=get_scopus_headers(),
        )

        return response.json()

    except Exception as exc:

        print(
            f"WARNING: Scopus search failed: {exc}"
        )

        return {}


def scopus_get_value(
    data,
    *keys,
):
    """
    Read a value from a Scopus response.

    Supports both direct values and nested dictionaries.
    """

    current = data

    for key in keys:

        if not isinstance(current, dict):
            return ""

        current = current.get(
            key
        )

    return clean_text(current)


def get_scopus_authors(data):
    """
    Extract authors from Scopus abstract metadata.

    Scopus commonly returns authors under:

        authors.author
    """

    authors_data = (
        data.get(
            "abstracts-retrieval-response",
            {},
        )
        .get(
            "authors",
            {},
        )
    )

    author_list = authors_data.get(
        "author",
        [],
    )

    if isinstance(
        author_list,
        dict,
    ):

        author_list = [
            author_list
        ]

    authors = []

    for author in author_list:

        if not isinstance(
            author,
            dict,
        ):
            continue

        surname = clean_text(
            author.get(
                "ce:surname",
                "",
            )
        )

        given = clean_text(
            author.get(
                "ce:given-name",
                "",
            )
        )

        indexed_name = clean_text(
            author.get(
                "ce:indexed-name",
                "",
            )
        )

        if indexed_name:

            authors.append(
                indexed_name
            )

        elif surname:

            initials = ""

            for part in re.split(
                r"[\s\-]+",
                given,
            ):

                if part:
                    initials += part[0].upper()

            if initials:

                authors.append(
                    f"{surname} {initials}"
                )

            else:

                authors.append(
                    surname
                )

    return ", ".join(authors)


def parse_scopus_metadata(data):
    """
    Convert Scopus response to our common metadata structure.
    """

    if not data:
        return {}

    root = data.get(
        "abstracts-retrieval-response",
        {},
    )

    if not root:
        return {}

    coredata = root.get(
        "coredata",
        {},
    )

    title = clean_text(
        coredata.get(
            "dc:title",
            "",
        )
    )

    authors = get_scopus_authors(
        data
    )

    journal = clean_text(
        coredata.get(
            "prism:publicationName",
            "",
        )
    )

    year = clean_text(
        coredata.get(
            "prism:coverDate",
            "",
        )
    )

    match = re.search(
        r"\b(19|20)\d{2}\b",
        year,
    )

    if match:
        year = match.group(0)

    volume = clean_text(
        coredata.get(
            "prism:volume",
            "",
        )
    )

    issue = clean_text(
        coredata.get(
            "prism:issueIdentifier",
            "",
        )
    )

    pages = clean_text(
        coredata.get(
            "prism:pageRange",
            "",
        )
    )

    if not pages:

        pages = clean_text(
            coredata.get(
                "prism:articleNumber",
                "",
            )
        )

    doi = clean_doi(
        coredata.get(
            "prism:doi",
            "",
        )
    )

    pmid = ""

    identifiers = root.get(
        "item",
        {},
    )

    if isinstance(
        identifiers,
        dict,
    ):

        identifiers = identifiers.get(
            "bibrecord",
            {},
        )

        if isinstance(
            identifiers,
            dict,
        ):

            item_info = identifiers.get(
                "item-info",
                {},
            )

            if isinstance(
                item_info,
                dict,
            ):

                db_ident = item_info.get(
                    "db-ident",
                    {},
                )

                if isinstance(
                    db_ident,
                    dict,
                ):

                    pmid = clean_text(
                        db_ident.get(
                            "ce:doi",
                            "",
                        )
                    )

    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": doi,
        "pmid": pmid,
    }


def get_scopus_metadata(
    doi="",
    pmid="",
    title="",
):
    """
    Retrieve Scopus metadata.

    Priority:

        DOI
        PMID
        exact-ish title search
    """

    if not scopus_available():
        return {}

    # --------------------------------------------------------
    # DOI
    # --------------------------------------------------------

    if doi:

        print(
            "  Scopus lookup by DOI..."
        )

        data = get_scopus_metadata_by_identifier(
            "doi",
            doi,
        )

        metadata = parse_scopus_metadata(
            data
        )

        if metadata:

            print(
                "  Scopus metadata: OK"
            )

            return metadata

    # --------------------------------------------------------
    # PMID
    # --------------------------------------------------------

    if pmid:

        print(
            "  Scopus lookup by PMID..."
        )

        data = get_scopus_metadata_by_identifier(
            "pubmed_id",
            pmid,
        )

        metadata = parse_scopus_metadata(
            data
        )

        if metadata:

            print(
                "  Scopus metadata: OK"
            )

            return metadata

    # --------------------------------------------------------
    # TITLE
    # --------------------------------------------------------

    if title:

        print(
            "  Scopus search by title..."
        )

        query = (
            f'TITLE("{title}")'
        )

        data = get_scopus_search(
            query
        )

        results = (
            data.get(
                "search-results",
                {},
            )
            .get(
                "entry",
                [],
            )
        )

        if isinstance(
            results,
            dict,
        ):

            results = [
                results
            ]

        normalized_target = normalize_title(
            title
        )

        best = None
        best_score = 0

        for result in results:

            candidate_title = clean_text(
                result.get(
                    "dc:title",
                    "",
                )
            )

            if not candidate_title:
                continue

            score = title_similarity(
                normalized_target,
                normalize_title(
                    candidate_title
                ),
            )

            if score > best_score:

                best_score = score
                best = result

        if best and best_score >= 0.85:

            metadata = {
                "title": clean_text(
                    best.get(
                        "dc:title",
                        "",
                    )
                ),
                "authors": clean_text(
                    best.get(
                        "dc:creator",
                        "",
                    )
                ),
                "journal": clean_text(
                    best.get(
                        "prism:publicationName",
                        "",
                    )
                ),
                "year": extract_year(
                    best.get(
                        "prism:coverDate",
                        "",
                    )
                ),
                "volume": clean_text(
                    best.get(
                        "prism:volume",
                        "",
                    )
                ),
                "issue": clean_text(
                    best.get(
                        "prism:issueIdentifier",
                        "",
                    )
                ),
                "pages": clean_text(
                    best.get(
                        "prism:pageRange",
                        "",
                    )
                ),
                "doi": clean_doi(
                    best.get(
                        "prism:doi",
                        "",
                    )
                ),
                "pmid": clean_text(
                    best.get(
                        "pubmed-id",
                        "",
                    )
                ),
            }

            print(
                f"  Scopus title match: OK "
                f"(score={best_score:.2f})"
            )

            return metadata

    return {}


# ============================================================
# TITLE MATCHING
# ============================================================

def normalize_title(title):

    title = clean_text(
        title
    ).lower()

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


def title_similarity(a, b):

    if not a or not b:
        return 0

    a_tokens = set(
        a.split()
    )

    b_tokens = set(
        b.split()
    )

    if not a_tokens or not b_tokens:
        return 0

    intersection = len(
        a_tokens & b_tokens
    )

    union = len(
        a_tokens | b_tokens
    )

    return intersection / union


def extract_year(value):

    match = re.search(
        r"\b(19|20)\d{2}\b",
        clean_text(value),
    )

    if match:
        return match.group(0)

    return ""


# ============================================================
# MERGING
# ============================================================

def first_nonempty(
    *values,
):
    """
    Return the first non-empty value.
    """

    for value in values:

        if value is None:
            continue

        value = clean_text(value)

        if value:
            return value

    return ""


def merge_publication(
    orcid_data,
    pubmed_data,
    crossref_data,
    scopus_data,
):
    """
    Merge metadata.

    Priority:

        ORCID
          ↓
        PubMed
          ↓
        Crossref
          ↓
        Scopus

    However, Scopus is explicitly used as a fallback for
    any field that is missing from the previous sources.
    """

    title = first_nonempty(
        orcid_data.get("title"),
        pubmed_data.get("title"),
        crossref_data.get("title", [""])[0]
        if crossref_data.get("title")
        else "",
        scopus_data.get("title"),
    )

    year = first_nonempty(
        orcid_data.get("year"),
        pubmed_data.get("year"),
        get_crossref_year(
            crossref_data
        ),
        scopus_data.get("year"),
    )

    journal = first_nonempty(
        orcid_data.get("journal"),
        pubmed_data.get("journal"),
        (
            crossref_data.get(
                "container-title",
                [""],
            )[0]
            if crossref_data.get(
                "container-title"
            )
            else ""
        ),
        scopus_data.get("journal"),
    )

    authors = first_nonempty(
        orcid_data.get("authors"),
        pubmed_data.get("authors"),
        format_crossref_authors(
            crossref_data
        ),
        scopus_data.get("authors"),
    )

    volume = first_nonempty(
        orcid_data.get("volume"),
        pubmed_data.get("volume"),
        crossref_data.get(
            "volume",
            "",
        ),
        scopus_data.get("volume"),
    )

    issue = first_nonempty(
        orcid_data.get("issue"),
        pubmed_data.get("issue"),
        crossref_data.get(
            "issue",
            "",
        ),
        scopus_data.get("issue"),
    )

    pages = first_nonempty(
        orcid_data.get("pages"),
        pubmed_data.get("pages"),
        crossref_data.get(
            "page",
            "",
        ),
        crossref_data.get(
            "article-number",
            "",
        ),
        scopus_data.get("pages"),
    )

    doi = first_nonempty(
        orcid_data.get("doi"),
        pubmed_data.get("doi"),
        crossref_data.get(
            "DOI",
            "",
        ),
        scopus_data.get("doi"),
    )

    pmid = first_nonempty(
        orcid_data.get("pmid"),
        pubmed_data.get("pmid"),
        scopus_data.get("pmid"),
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
        "pmid": clean_text(pmid),
    }


# ============================================================
# FIELD COMPLETENESS
# ============================================================

def publication_missing_data(
    publication,
):
    """
    Return True when at least one important field is missing.
    """

    important_fields = (
        "title",
        "authors",
        "journal",
        "year",
        "doi",
        "pmid",
    )

    return any(
        not clean_text(
            publication.get(
                field,
                "",
            )
        )
        for field in important_fields
    )


# ============================================================
# MAIN
# ============================================================

def main():

    groups = get_orcid_works()

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # No SystemExit / exit(1).
    #
    # If ORCID is unavailable, create/keep an empty YAML
    # and return normally.
    # --------------------------------------------------------

    if not groups:

        print(
            "WARNING: ORCID returned no publications."
        )

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
                    [],
                    file,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )

            print(
                f"Saved empty publication list to: {OUTPUT}"
            )

        except Exception as exc:

            print(
                f"WARNING: Could not save YAML: {exc}"
            )

        return

    publications = []

    print()
    print("=" * 60)
    print("Processing publications")
    print("=" * 60)

    if SCOPUS_API_KEY:

        print(
            "Scopus fallback: ENABLED"
        )

    else:

        print(
            "Scopus fallback: DISABLED "
            "(SCOPUS_API_KEY missing)"
        )

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
            f"{summary_title}"
        )

        # ----------------------------------------------------
        # ORCID DETAIL
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

        orcid_data = {
            "title": get_work_title(
                work
            ),
            "year": get_work_year(
                work
            ),
            "journal": get_work_journal(
                work
            ),
            "doi": get_doi(
                work
            ),
            "pmid": get_pmid(
                work
            ),
            "authors": get_orcid_authors(
                work
            ),
        }

        print(
            "  ORCID authors: "
            f"{'FOUND' if orcid_data['authors'] else 'MISSING'}"
        )

        print(
            "  ORCID DOI:     "
            f"{orcid_data['doi'] or '-'}"
        )

        print(
            "  ORCID PMID:    "
            f"{orcid_data['pmid'] or '-'}"
        )

        # ----------------------------------------------------
        # PMID LOOKUP
        # ----------------------------------------------------

        pmid = orcid_data["pmid"]

        if not pmid:

            if orcid_data["doi"]:

                print(
                    "  Looking up PMID from DOI..."
                )

                try:

                    pmid = get_pmid_from_doi(
                        orcid_data["doi"]
                    )

                except Exception as exc:

                    print(
                        f"  WARNING: PMID lookup failed: {exc}"
                    )

            if not pmid and orcid_data["title"]:

                print(
                    "  Looking up PMID from title..."
                )

                try:

                    pmid = get_pmid_from_title(
                        orcid_data["title"]
                    )

                except Exception as exc:

                    print(
                        f"  WARNING: PMID title search failed: {exc}"
                    )

        if pmid:

            orcid_data["pmid"] = pmid

            print(
                f"  PMID: {pmid}"
            )

        # ----------------------------------------------------
        # PUBMED
        # ----------------------------------------------------

        pubmed_data = {}

        if pmid:

            print(
                "  Fetching PubMed metadata..."
            )

            try:

                pubmed_data = get_pubmed_metadata(
                    pmid
                )

            except Exception as exc:

                print(
                    f"  WARNING: PubMed failed: {exc}"
                )

            if pubmed_data:

                print(
                    "  PubMed metadata: OK"
                )

        # ----------------------------------------------------
        # CROSSREF
        # ----------------------------------------------------

        crossref_data = {}

        doi = orcid_data["doi"]

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

        elif not pubmed_data:

            print(
                "  Searching Crossref by title..."
            )

            crossref_data = (
                get_crossref_metadata_by_title(
                    orcid_data["title"]
                )
            )

            if crossref_data:

                print(
                    "  Crossref title match: OK"
                )

        # ----------------------------------------------------
        # PRELIMINARY MERGE
        # ----------------------------------------------------

        preliminary = merge_publication(
            orcid_data,
            pubmed_data,
            crossref_data,
            {},
        )

        # ----------------------------------------------------
        # SCOPUS
        #
        # Use Scopus if ANY important data is missing.
        # ----------------------------------------------------

        scopus_data = {}

        if SCOPUS_API_KEY:

            if publication_missing_data(
                preliminary
            ):

                scopus_data = get_scopus_metadata(
                    doi=preliminary["doi"],
                    pmid=preliminary["pmid"],
                    title=preliminary["title"],
                )

                if not scopus_data:

                    print(
                        "  Scopus: no matching metadata"
                    )

            else:

                print(
                    "  Scopus: not needed"
                )

        # ----------------------------------------------------
        # FINAL MERGE
        # ----------------------------------------------------

        publication = merge_publication(
            orcid_data,
            pubmed_data,
            crossref_data,
            scopus_data,
        )

        # ----------------------------------------------------
        # REPORT
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

        publications.append(
            publication
        )

    # ========================================================
    # REMOVE DUPLICATES
    # ========================================================

    unique = {}

    for publication in publications:

        doi = publication.get(
            "doi",
            "",
        )

        pmid = publication.get(
            "pmid",
            "",
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

                # Keep records even if everything is missing.
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

    def year_sort_key(
        publication,
    ):

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
    #
    # Validation produces warnings only.
    # It NEVER exits with code 1.
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

    missing_journals = [
        publication
        for publication in publications
        if not publication.get("journal")
    ]

    missing_years = [
        publication
        for publication in publications
        if not publication.get("year")
    ]

    missing_identifiers = [
        publication
        for publication in publications
        if (
            not publication.get("doi")
            and not publication.get("pmid")
        )
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
                    or "(untitled)"
                )
            )

    if missing_journals:

        print(
            f"WARNING: {len(missing_journals)} "
            f"publications have no journal."
        )

    if missing_years:

        print(
            f"WARNING: {len(missing_years)} "
            f"publications have no year."
        )

    if missing_identifiers:

        print(
            f"WARNING: {len(missing_identifiers)} "
            f"publications have neither DOI nor PMID."
        )

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

        return

    # ========================================================
    # FINAL STATUS
    # ========================================================

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)

    print(
        f"Updated {len(publications)} publications"
    )

    print(
        f"Saved to: {OUTPUT}"
    )

    print(
        "Missing metadata is treated as WARNING only."
    )

    print(
        "Script finished normally."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
```
