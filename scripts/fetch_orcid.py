from pathlib import Path
import re
import time

import requests
import yaml


# ============================================================
# CONFIGURATION
# ============================================================

ORCID_ID = "0000-0002-7470-177X"

ORCID_URL = (
    f"https://pub.orcid.org/v3.0/{ORCID_ID}/works"
    "?rows=200"
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

CROSSREF_URL = "https://api.crossref.org/works/"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VanharaLab-publications/1.0"
}


# ============================================================
# HELPERS
# ============================================================

def clean_doi(doi):
    """Normalize DOI without changing its identity."""

    if not doi:
        return ""

    doi = doi.strip()

    doi = re.sub(
        r"^https?://doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE
    )

    doi = re.sub(
        r"^doi:\s*",
        "",
        doi,
        flags=re.IGNORECASE
    )

    return doi.strip()


def get_orcid_works():
    """Download publication list from ORCID."""

    print("Fetching publications from ORCID...")

    response = requests.get(
        ORCID_URL,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def get_doi(work):
    """Extract DOI from an ORCID work."""

    external_ids = (
        work.get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:

        id_type = (
            external_id
            .get("external-id-type", "")
            .lower()
            .strip()
        )

        if id_type == "doi":

            value = external_id.get(
                "external-id-value",
                ""
            )

            return clean_doi(value)

    return ""


def get_orcid_title(work):
    return (
        work.get("title", {})
        .get("title", {})
        .get("value", "")
        .strip()
    )


def get_orcid_year(work):

    publication_date = work.get(
        "publication-date"
    )

    if not publication_date:
        return ""

    return (
        publication_date
        .get("year", {})
        .get("value", "")
    )


def get_orcid_journal(work):

    journal = work.get(
        "journal-title"
    )

    if not journal:
        return ""

    return (
        journal
        .get("value", "")
        .strip()
    )


def get_crossref_metadata(doi):
    """Get bibliographic metadata from Crossref."""

    if not doi:
        return {}

    print(f"  Crossref: {doi}")

    url = CROSSREF_URL + doi

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    if response.status_code != 200:
        print(
            f"  WARNING: Crossref lookup failed: "
            f"{response.status_code}"
        )
        return {}

    return response.json().get(
        "message",
        {}
    )


def format_crossref_authors(metadata):
    """Format Crossref authors as Surname Initials."""

    authors = []

    for author in metadata.get(
        "author",
        []
    ):

        family = author.get(
            "family",
            ""
        ).strip()

        given = author.get(
            "given",
            ""
        ).strip()

        if not family:
            continue

        initials = ""

        for part in re.split(
            r"[\s-]+",
            given
        ):

            part = part.strip()

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


def get_pubmed_by_doi(doi):
    """Find PubMed record using DOI."""

    if not doi:
        return None

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1
    }

    response = requests.get(
        PUBMED_ESEARCH_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    ids = (
        response.json()
        .get("esearchresult", {})
        .get("idlist", [])
    )

    if not ids:
        return None

    return ids[0]


def get_pubmed_by_title(title):
    """Fallback: find PubMed record using exact title."""

    if not title:
        return None

    params = {
        "db": "pubmed",
        "term": f'"{title}"[Title]',
        "retmode": "json",
        "retmax": 1
    }

    response = requests.get(
        PUBMED_ESEARCH_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    ids = (
        response.json()
        .get("esearchresult", {})
        .get("idlist", [])
    )

    if not ids:
        return None

    return ids[0]


def get_pubmed_metadata(pmid):
    """Download full PubMed metadata."""

    if not pmid:
        return {}

    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml"
    }

    response = requests.get(
        PUBMED_EFETCH_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    import xml.etree.ElementTree as ET

    root = ET.fromstring(
        response.text
    )

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

    title = art.findtext(
        "ArticleTitle",
        default=""
    )

    journal = art.findtext(
        ".//Journal/Title",
        default=""
    )

    year = art.findtext(
        ".//PubDate/Year",
        default=""
    )

    volume = art.findtext(
        ".//JournalIssue/Volume",
        default=""
    )

    issue = art.findtext(
        ".//JournalIssue/Issue",
        default=""
    )

    pages = art.findtext(
        ".//Pagination/MedlinePgn",
        default=""
    )

    authors = []

    for author in art.findall(
        ".//Author"
    ):

        lastname = author.findtext(
            "LastName"
        )

        initials = author.findtext(
            "Initials"
        )

        if lastname:

            name = lastname.strip()

            if initials:
                name += (
                    f" {initials.strip()}"
                )

            authors.append(name)

    return {
        "title": title,
        "journal": journal,
        "year": year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "authors": ", ".join(authors),
        "pmid": article.findtext(
            ".//PMID",
            default=pmid
        )
    }


# ============================================================
# MAIN
# ============================================================

data = get_orcid_works()

groups = data.get(
    "group",
    []
)

print(
    f"ORCID works found: {len(groups)}"
)

publications = []


for group in groups:

    summaries = group.get(
        "work-summary",
        []
    )

    if not summaries:
        continue

    work = summaries[0]

    orcid_title = get_orcid_title(
        work
    )

    orcid_year = get_orcid_year(
        work
    )

    orcid_journal = get_orcid_journal(
        work
    )

    doi = get_doi(work)

    print()
    print(
        f"Processing: {orcid_title}"
    )
    print(
        f"  DOI: {doi or '(none)'}"
    )

    # --------------------------------------------------------
    # CROSSREF
    # --------------------------------------------------------

    crossref = get_crossref_metadata(
        doi
    )

    crossref_title = ""

    if crossref.get("title"):
        crossref_title = (
            crossref["title"][0]
            .strip()
        )

    crossref_journal = ""

    if crossref.get(
        "container-title"
    ):

        crossref_journal = (
            crossref["container-title"][0]
            .strip()
        )

    crossref_year = ""

    published = crossref.get(
        "published-print"
    ) or crossref.get(
        "published-online"
    ) or crossref.get(
        "issued"
    )

    if published:

        date_parts = published.get(
            "date-parts",
            []
        )

        if date_parts and date_parts[0]:

            crossref_year = str(
                date_parts[0][0]
            )

    authors = format_crossref_authors(
        crossref
    )

    volume = crossref.get(
        "volume",
        ""
    )

    issue = crossref.get(
        "issue",
        ""
    )

    pages = (
        crossref.get("page")
        or crossref.get("article-number")
        or ""
    )

    # --------------------------------------------------------
    # PUBMED
    # --------------------------------------------------------

    pmid = ""

    pubmed = {}

    if doi:

        pmid = get_pubmed_by_doi(
            doi
        )

        if pmid:
            print(
                f"  PMID: {pmid}"
            )

            pubmed = get_pubmed_metadata(
                pmid
            )

        else:
            print(
                f"  PMID: not found"
            )

    # If DOI is missing, try title search.
    elif orcid_title:

        print(
            "  No DOI - searching PubMed by title"
        )

        pmid = get_pubmed_by_title(
            orcid_title
        )

        if pmid:

            print(
                f"  PMID: {pmid}"
            )

            pubmed = get_pubmed_metadata(
                pmid
            )

        else:

            print(
                "  PMID: not found"
            )

    # --------------------------------------------------------
    # CHOOSE BEST METADATA
    #
    # Priority:
    # PubMed → Crossref → ORCID
    # --------------------------------------------------------

    title = (
        pubmed.get("title")
        or crossref_title
        or orcid_title
    )

    journal = (
        pubmed.get("journal")
        or crossref_journal
        or orcid_journal
    )

    year = (
        pubmed.get("year")
        or crossref_year
        or orcid_year
    )

    final_authors = (
        pubmed.get("authors")
        or authors
    )

    final_volume = (
        pubmed.get("volume")
        or volume
    )

    final_issue = (
        pubmed.get("issue")
        or issue
    )

    final_pages = (
        pubmed.get("pages")
        or pages
    )

    publication = {
        "year": str(year),
        "title": title,
        "authors": final_authors,
        "journal": journal,
        "volume": final_volume,
        "issue": final_issue,
        "pages": final_pages,
        "doi": doi,
        "pmid": pmid or ""
    }

    publications.append(
        publication
    )

    print(
        f"  OK: {title}"
    )

    # Avoid hammering APIs
    time.sleep(0.2)


# ============================================================
# REMOVE DUPLICATES
# ============================================================

unique = {}

for publication in publications:

    doi = clean_doi(
        publication.get(
            "doi",
            ""
        )
    )

    if doi:

        key = (
            "doi:"
            + doi.lower()
        )

    else:

        title = publication.get(
            "title",
            ""
        ).strip().lower()

        key = (
            "title:"
            + title
        )

    unique[key] = publication


publications = list(
    unique.values()
)


# ============================================================
# SORT
# ============================================================

def year_key(publication):

    try:
        return int(
            publication.get(
                "year",
                ""
            )
        )

    except (ValueError, TypeError):

        return 0


publications.sort(
    key=year_key,
    reverse=True
)


# ============================================================
# SAVE
# ============================================================

base_dir = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

output = (
    base_dir
    / "_data"
    / "publications.yml"
)

output.parent.mkdir(
    parents=True,
    exist_ok=True
)

with open(
    output,
    "w",
    encoding="utf-8"
) as file:

    yaml.dump(
        publications,
        file,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False
    )


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 60)
print(
    f"Updated {len(publications)} publications"
)
print(
    f"Saved to: {output}"
)
print("=" * 60)

doi_count = sum(
    1
    for p in publications
    if p.get("doi")
)

pmid_count = sum(
    1
    for p in publications
    if p.get("pmid")
)

author_count = sum(
    1
    for p in publications
    if p.get("authors")
)

print(
    f"With DOI:     {doi_count}"
)

print(
    f"With PMID:    {pmid_count}"
)

print(
    f"With authors: {author_count}"
)
