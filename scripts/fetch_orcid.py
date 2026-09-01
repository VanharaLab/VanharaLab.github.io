from pathlib import Path
import html
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

SCOPUS_SEARCH_URL = "https://api.elsevier.com/content/search/scopus"

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "_data"
    / "publications.yml"
)

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
SCOPUS_DELAY = 0.2

MAX_RETRIES = 5

SCOPUS_API_KEY = ""


# ============================================================
# HTTP
# ============================================================

def get_request(url, *, params=None, headers=None):
    """
    GET request with retry handling.

    Returns None instead of raising an exception after all
    retries. This prevents the complete workflow from failing
    because one external service is temporarily unavailable.
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
                print(
                    f"WARNING: Request failed after "
                    f"{MAX_RETRIES} attempts: {exc}"
                )
                return None

            wait = 2 ** attempt

            print(
                f"WARNING: Request failed: {exc}. "
                f"Retrying in {wait} seconds..."
            )

            time.sleep(wait)

    return None


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

        response = get_request(
            ORCID_WORKS_URL,
            params=params,
            headers=HEADERS,
        )

        if response is None:
            print(
                "WARNING: ORCID request failed."
            )
            break

        try:
            data = response.json()
        except ValueError:
            print(
                "WARNING: ORCID returned invalid JSON."
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


def get_external_id(work, wanted_type):
    """
    Get an external identifier from ORCID.
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
                {}
            ).get(
                "value",
                "",
            )
        )

        if credit_name:
            authors.append(credit_name)
            continue

        contributor_name = clean_text(
            contributor.get(
                "contributor-name",
                {}
            ).get(
                "value",
                "",
            )
        )

        if contributor_name:
            authors.append(contributor_name)

    return ", ".join(authors)


def get_orcid_work_detail(summary):
    """
    Fetch full ORCID work record.
    """

    put_code = summary.get(
        "put-code"
    )

    if not put_code:
        return {}

    url = (
        f"{ORCID_API}/{ORCID_ID}"
        f"/work/{put_code}"
    )

    response = get_request(
        url,
        headers=HEADERS,
    )

    if response is None:
        return {}

    try:
        return response.json()
    except ValueError:
        return {}


# ============================================================
# PUBMED
# ============================================================

def get_pmid_from_doi(doi):
    """
    Find PMID from DOI.
    """

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

    if response is None:
        return ""

    try:
        data = response.json()
    except ValueError:
        return ""

    ids = (
        data.get("esearchresult", {})
        .get("idlist", [])
    )

    if ids:
        return str(ids[0])

    return ""


def get_pmid_from_title(title):
    """
    Find PMID using publication title.
    """

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

    if response is None:
        return ""

    try:
        data = response.json()
    except ValueError:
        return ""

    ids = (
        data.get("esearchresult", {})
        .get("idlist", [])
    )

    if ids:
        return str(ids[0])

    return ""


def get_pubmed_metadata(pmid):
    """
    Retrieve complete metadata from PubMed.
    """

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

    if response is None:
        return {}

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

    title_element = art.find(
        "ArticleTitle"
    )

    title = ""

    if title_element is not None:
        title = clean_text(
            "".join(
                title_element.itertext()
            )
        )

    journal = clean_text(
        art.findtext(
            ".//Journal/Title",
            default="",
        )
    )

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

    volume = clean_text(
        art.findtext(
            ".//JournalIssue/Volume",
            default="",
        )
    )

    issue = clean_text(
        art.findtext(
            ".//JournalIssue/Issue",
            default="",
        )
    )

    pages = clean_text(
        art.findtext(
            ".//Pagination/MedlinePgn",
            default="",
        )
    )

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
                authors.append(lastname)

        elif collective:
            authors.append(collective)

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
    """
    Retrieve metadata from Crossref using DOI.
    """

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

    response = get_request(
        url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
        },
    )

    if response is None:
        return {}

    try:
        return response.json().get(
            "message",
            {}
        )
    except ValueError:
        return {}


def get_crossref_metadata_by_title(title):
    """
    Search Crossref by title.
    """

    if not title:
        return {}

    params = {
        "query.title": title,
        "rows": 5,
    }

    time.sleep(CROSSREF_DELAY)

    response = get_request(
        CROSSREF_SEARCH_URL,
        params=params,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
        },
    )

    if response is None:
        return {}

    try:
        items = (
            response.json()
            .get("message", {})
            .get("items", [])
        )
    except ValueError:
        return {}

    if not items:
        return {}

    normalized_target = normalize_title(title)

    best_item = None
    best_score = 0

    for item in items:
        item_titles = item.get(
            "title",
            []
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

    return {}


def format_crossref_authors(metadata):
    """
    Format Crossref authors.
    """

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
            authors.append(family)

    return ", ".join(authors)


def get_crossref_year(metadata):
    """
    Extract publication year from Crossref.
    """

    for key in (
        "published-print",
        "published-online",
        "published",
        "issued",
    ):
        date_parts = (
            metadata.get(
                key,
                {}
            )
            .get(
                "date-parts",
                []
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

def scopus_enabled():
    """
    Check whether Scopus API is configured.
    """

    return bool(
        SCOPUS_API_KEY
        and SCOPUS_API_KEY.strip()
    )


def get_scopus_metadata(
    *,
    doi="",
    title="",
):
    """
    Retrieve publication metadata from Scopus.

    DOI is preferred. Title is used as fallback.

    If no SCOPUS_API_KEY is configured, this function
    silently returns an empty dictionary.
    """

    if not scopus_enabled():
        return {}

    if not doi and not title:
        return {}

    time.sleep(SCOPUS_DELAY)

    headers = {
        "Accept": "application/json",
        "X-ELS-APIKey": SCOPUS_API_KEY,
    }

    if doi:
        query = f'DOI("{doi}")'
    else:
        query = f'TITLE("{title}")'

    params = {
        "query": query,
        "count": 5,
        "view": "COMPLETE",
    }

    response = get_request(
        SCOPUS_SEARCH_URL,
        params=params,
        headers=headers,
    )

    if response is None:
        return {}

    try:
        data = response.json()
    except ValueError:
        print(
            "WARNING: Scopus returned invalid JSON."
        )
        return {}

    entries = (
        data.get("search-results", {})
        .get("entry", [])
    )

    if not entries:
        return {}

    normalized_target = normalize_title(title)

    best = None
    best_score = 0

    for entry in entries:
        candidate_title = clean_text(
            entry.get(
                "dc:title",
                "",
            )
        )

        if title and candidate_title:
            score = title_similarity(
                normalized_target,
                normalize_title(candidate_title),
            )
        else:
            score = 1

        if score > best_score:
            best_score = score
            best = entry

    if best is None:
        return {}

    if title and best_score < 0.80:
        return {}

    authors = []

    author_entries = (
        best.get("author", [])
    )

    if isinstance(
        author_entries,
        dict,
    ):
        author_entries = [
            author_entries
        ]

    for author in author_entries:
        surname = clean_text(
            author.get(
                "surname",
                "",
            )
        )

        given = clean_text(
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
            elif given:
                given_initials = "".join(
                    part[0].upper()
                    for part in re.split(
                        r"[\s\-]+",
                        given,
                    )
                    if part
                )

                if given_initials:
                    authors.append(
                        f"{surname} {given_initials}"
                    )
                else:
                    authors.append(surname)

    publication_name = clean_text(
        best.get(
            "prism:publicationName",
            "",
        )
    )

    publication_year = clean_text(
        best.get(
            "prism:coverDate",
            "",
        )
    )

    year_match = re.search(
        r"\b(19|20)\d{2}\b",
        publication_year,
    )

    if year_match:
        publication_year = year_match.group(0)

    volume = clean_text(
        best.get(
            "prism:volume",
            "",
        )
    )

    issue = clean_text(
        best.get(
            "prism:issueIdentifier",
            "",
        )
    )

    pages = clean_text(
        best.get(
            "prism:pageRange",
            "",
        )
    )

    article_number = clean_text(
        best.get(
            "article-number",
            "",
        )
    )

    if not pages:
        pages = article_number

    scopus_doi = clean_doi(
        best.get(
            "prism:doi",
            "",
        )
    )

    scopus_pmid = clean_text(
        best.get(
            "pubmed-id",
            "",
        )
    )

    return {
        "title": clean_text(
            best.get(
                "dc:title",
                "",
            )
        ),
        "authors": ", ".join(authors),
        "journal": publication_name,
        "year": publication_year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "doi": scopus_doi,
        "pmid": scopus_pmid,
    }


# ============================================================
# TITLE MATCHING
# ============================================================

def normalize_title(title):
    """
    Normalize title for comparison.
    """

    title = clean_text(title).lower()

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
    """
    Token-based Jaccard similarity.
    """

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


# ============================================================
# MERGING
# ============================================================

def merge_publication(
    orcid_data,
    pubmed_data,
    crossref_data,
    scopus_data,
):
    """
    Merge metadata using this priority:

        ORCID
          ↓
        PubMed
          ↓
        Scopus
          ↓
        Crossref

    ORCID remains the primary source.
    """

    crossref_title = ""

    if crossref_data.get("title"):
        crossref_title = clean_text(
            crossref_data["title"][0]
        )

    crossref_journal = ""

    if crossref_data.get(
        "container-title"
    ):
        crossref_journal = clean_text(
            crossref_data[
                "container-title"
            ][0]
        )

    title = (
        orcid_data.get("title")
        or pubmed_data.get("title")
        or scopus_data.get("title")
        or crossref_title
    )

    year = (
        orcid_data.get("year")
        or pubmed_data.get("year")
        or scopus_data.get("year")
        or get_crossref_year(
            crossref_data
        )
    )

    journal = (
        orcid_data.get("journal")
        or pubmed_data.get("journal")
        or scopus_data.get("journal")
        or crossref_journal
    )

    authors = (
        orcid_data.get("authors")
        or pubmed_data.get("authors")
        or scopus_data.get("authors")
        or format_crossref_authors(
            crossref_data
        )
    )

    volume = (
        orcid_data.get("volume")
        or pubmed_data.get("volume")
        or scopus_data.get("volume")
        or clean_text(
            crossref_data.get(
                "volume",
                "",
            )
        )
    )

    issue = (
        orcid_data.get("issue")
        or pubmed_data.get("issue")
        or scopus_data.get("issue")
        or clean_text(
            crossref_data.get(
                "issue",
                "",
            )
        )
    )

    pages = (
        orcid_data.get("pages")
        or pubmed_data.get("pages")
        or scopus_data.get("pages")
        or clean_text(
            crossref_data.get(
                "page",
                "",
            )
        )
        or clean_text(
            crossref_data.get(
                "article-number",
                "",
            )
        )
    )

    doi = (
        orcid_data.get("doi")
        or pubmed_data.get("doi")
        or scopus_data.get("doi")
        or clean_text(
            crossref_data.get(
                "DOI",
                "",
            )
        )
    )

    pmid = (
        orcid_data.get("pmid")
        or pubmed_data.get("pmid")
        or scopus_data.get("pmid")
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
# MAIN
# ============================================================

def main():
    groups = get_orcid_works()

    if not groups:
        print(
            "WARNING: ORCID returned no publications."
        )
        print(
            "Nothing to update."
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
            f"{summary_title}"
        )

        # ----------------------------------------------------
        # FULL ORCID RECORD
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
        # CROSSREF
        # ----------------------------------------------------

        crossref_data = {}

        if doi:
            print(
                "  Fetching Crossref metadata..."
            )

            crossref_data = get_crossref_metadata(
                doi
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
                    title
                )
            )

            if crossref_data:
                print(
                    "  Crossref title match: OK"
                )

        # ----------------------------------------------------
        # SCOPUS
        # ----------------------------------------------------

        scopus_data = {}

        if scopus_enabled():
            print(
                "  Searching Scopus..."
            )

            scopus_data = get_scopus_metadata(
                doi=doi,
                title=title,
            )

            if scopus_data:
                print(
                    "  Scopus metadata: OK"
                )

                if scopus_data.get(
                    "authors"
                ):
                    print(
                        "  Scopus authors: FOUND"
                    )
        else:
            print(
                "  Scopus: not configured"
            )

        # ----------------------------------------------------
        # MERGE
        # ----------------------------------------------------

        publication = merge_publication(
            orcid_data,
            pubmed_data,
            crossref_data,
            scopus_data,
        )

        # ----------------------------------------------------
        # SOURCE REPORT
        # ----------------------------------------------------

        print(
            "  Final authors: "
            f"{publication['authors'] or 'MISSING'}"
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
            key = "doi:" + doi.lower()

        elif pmid:
            key = "pmid:" + pmid

        else:
            normalized = normalize_title(
                title
            )

            if normalized:
                key = "title:" + normalized
            else:
                key = (
                    "unknown:"
                    + str(len(unique))
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
        if not publication["title"]
    ]

    missing_authors = [
        publication
        for publication in publications
        if not publication["authors"]
    ]

    missing_journals = [
        publication
        for publication in publications
        if not publication["journal"]
    ]

    missing_years = [
        publication
        for publication in publications
        if not publication["year"]
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
                    publication["title"]
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

    # ========================================================
    # SAVE YAML
    # ========================================================

    try:
        OUTPUT.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

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

    except OSError as exc:
        print(
            f"WARNING: Could not save YAML: {exc}"
        )
        return 0

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

    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print()
        print("=" * 60)
        print("WARNING")
        print("=" * 60)
        print(
            f"Unexpected error: {exc}"
        )
        print(
            "The script will finish without exit code 1."
        )
        print("=" * 60)
