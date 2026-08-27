from pathlib import Path
import html
import re
import time

import requests
import yaml
import xml.etree.ElementTree as ET


# ============================================================
# CONFIGURATION
# ============================================================

ORCID_ID = "0000-0002-7470-177X"

ORCID_URL = (
    f"https://pub.orcid.org/v3.0/{ORCID_ID}/works"
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

CROSSREF_URL = "https://api.crossref.org/works/"

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

# ORCID pagination
PAGE_SIZE = 100

# PubMed requests must be gentle to avoid HTTP 429
PUBMED_DELAY = 0.4

# Retry settings
MAX_RETRIES = 5


# ============================================================
# HTTP HELPERS
# ============================================================

def get_request(url, *, params=None, headers=None):
    """
    GET request with retry handling.

    Especially important for PubMed, which may return HTTP 429.
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

    raise RuntimeError("Request failed after retries")


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(value):
    """
    Clean HTML/XML artifacts and whitespace.
    """

    if value is None:
        return ""

    value = str(value)

    # Decode HTML entities such as &amp;
    value = html.unescape(value)

    # Remove common XML/HTML tags
    value = re.sub(
        r"<[^>]+>",
        "",
        value,
    )

    # Remove XML escape artifacts
    value = value.replace(
        "\\n",
        " ",
    )

    # Collapse whitespace
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

    doi = doi.replace(
        "https://doi.org/",
        "",
    )

    doi = doi.replace(
        "http://doi.org/",
        "",
    )

    doi = doi.replace(
        "doi:",
        "",
    )

    return doi.strip()


# ============================================================
# ORCID
# ============================================================

def get_orcid_works():
    """
    Download ALL works from ORCID using pagination.
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
            ORCID_URL,
            params=params,
            headers=HEADERS,
        )

        data = response.json()

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


# ============================================================
# ORCID HELPERS
# ============================================================

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
    Return external ID from ORCID.

    Example:
        DOI
        PMID
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

            value = clean_text(
                external_id.get(
                    "external-id-value",
                    "",
                )
            )

            return value

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
    Extract authors if available in ORCID summary.

    ORCID summaries often do not contain complete author
    information, therefore PubMed/Crossref may later replace it.
    """

    authors = []

    contributors = work.get(
        "contributors",
        {}
    ).get(
        "contributor",
        []
    )

    for contributor in contributors:

        credit_name = (
            contributor.get(
                "credit-name",
                {}
            )
            .get("value", "")
        )

        credit_name = clean_text(
            credit_name
        )

        if credit_name:
            authors.append(
                credit_name
            )

    return ", ".join(authors)


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

    data = response.json()

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

    Returns an empty dictionary if PubMed does not contain
    the requested article.
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

    try:
        root = ET.fromstring(
            response.text
        )
    except ET.ParseError:
        print(
            f"WARNING: Could not parse PubMed XML for PMID {pmid}"
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

    # Some PubMed records use MedlineDate instead of Year
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
    """
    Retrieve metadata from Crossref.

    Crossref is used only as a fallback/supplement.
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
            {}
        )

    except Exception as exc:

        print(
            f"WARNING: Crossref failed for {doi}: {exc}"
        )

        return {}


def format_crossref_authors(metadata):
    """
    Format Crossref authors as:
    Surname AB, Surname CD
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

        # If Crossref provides an ORCID/initial-like family name,
        # retain the surname and construct initials from given name.
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


# ============================================================
# MERGING
# ============================================================

def merge_publication(
    orcid_data,
    pubmed_data,
    crossref_data,
):
    """
    Merge metadata.

    Priority:

        PubMed
          ↓
        Crossref
          ↓
        ORCID

    ORCID remains the source that guarantees that the work
    exists in the final list.
    """

    title = (
        pubmed_data.get("title")
        or (
            clean_text(
                crossref_data.get(
                    "title",
                    [""] ,
                )[0]
            )
            if crossref_data.get("title")
            else ""
        )
        or orcid_data.get(
            "title",
            "",
        )
    )

    year = (
        pubmed_data.get("year")
        or orcid_data.get(
            "year",
            "",
        )
    )

    journal = (
        pubmed_data.get("journal")
        or (
            clean_text(
                crossref_data.get(
                    "container-title",
                    [""],
                )[0]
            )
            if crossref_data.get(
                "container-title"
            )
            else ""
        )
        or orcid_data.get(
            "journal",
            "",
        )
    )

    authors = (
        pubmed_data.get("authors")
        or format_crossref_authors(
            crossref_data
        )
        or orcid_data.get(
            "authors",
            "",
        )
    )

    volume = (
        pubmed_data.get("volume")
        or clean_text(
            crossref_data.get(
                "volume",
                "",
            )
        )
    )

    issue = (
        pubmed_data.get("issue")
        or clean_text(
            crossref_data.get(
                "issue",
                "",
            )
        )
    )

    pages = (
        pubmed_data.get("pages")
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
    )

    pmid = (
        orcid_data.get("pmid")
        or pubmed_data.get("pmid")
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

        raise SystemExit(
            "ERROR: ORCID returned no publications."
        )

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

        # ----------------------------------------------------
        # ORCID can have multiple summaries in one group.
        # We inspect the first one because all summaries in
        # a group represent the same work.
        # ----------------------------------------------------

        work = summaries[0]

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

        orcid_data = {
            "title": title,
            "year": year,
            "journal": journal,
            "doi": doi,
            "pmid": pmid,
            "authors": get_orcid_authors(
                work
            ),
        }

        print()
        print(
            f"[{index}/{len(groups)}] {title}"
        )

        print(
            f"  ORCID DOI:  {doi or '-'}"
        )

        print(
            f"  ORCID PMID: {pmid or '-'}"
        )

        # ----------------------------------------------------
        # PMID
        # ----------------------------------------------------

        if not pmid and doi:

            print(
                f"  Looking up PMID from DOI..."
            )

            pmid = get_pmid_from_doi(
                doi
            )

            orcid_data["pmid"] = pmid

            if pmid:
                print(
                    f"  Found PMID: {pmid}"
                )

        # ----------------------------------------------------
        # PubMed
        # ----------------------------------------------------

        pubmed_data = {}

        if pmid:

            print(
                f"  Fetching PubMed metadata..."
            )

            try:

                pubmed_data = (
                    get_pubmed_metadata(
                        pmid
                    )
                )

            except requests.HTTPError as exc:

                print(
                    f"  WARNING: PubMed request failed: {exc}"
                )

            if pubmed_data:

                print(
                    "  PubMed metadata: OK"
                )

        # ----------------------------------------------------
        # Crossref
        # ----------------------------------------------------

        crossref_data = {}

        if doi:

            print(
                f"  Fetching Crossref metadata..."
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

        # ----------------------------------------------------
        # Merge
        # ----------------------------------------------------

        publication = merge_publication(
            orcid_data,
            pubmed_data,
            crossref_data,
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

            key = (
                "title:"
                + title.lower()
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

    if missing_titles:

        print(
            f"WARNING: {len(missing_titles)} "
            f"publications have no title."
        )

    # ========================================================
    # SAVE YAML
    # ========================================================

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


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
