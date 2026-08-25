from pathlib import Path
import time

import requests
import yaml
import xml.etree.ElementTree as ET


# ============================================================
# CONFIG
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

OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "_data"
    / "publications.yml"
)


# ============================================================
# HTTP SETTINGS
# ============================================================

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "VanharaLab-publications/1.0 "
        "(https://vanharalab.github.io/)"
    )
}

PUBMED_HEADERS = {
    "Accept": "application/xml",
    "User-Agent": (
        "VanharaLab-publications/1.0 "
        "(https://vanharalab.github.io/)"
    )
}

SESSION = requests.Session()


# PubMed limituje počet požadavků.
# Proto mezi nimi čekáme.
PUBMED_DELAY = 1.0

# Počet pokusů při 429 / 5xx
MAX_RETRIES = 5


# ============================================================
# HTTP HELPER
# ============================================================

def request_with_retry(
    url,
    *,
    params=None,
    headers=None,
    timeout=30,
    retries=MAX_RETRIES,
    delay=1.0
):
    """
    HTTP GET s retry.
    Zvlášť řeší 429 Too Many Requests.
    """

    for attempt in range(1, retries + 1):

        try:

            response = SESSION.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout
            )

            # ------------------------------------------------
            # OK
            # ------------------------------------------------

            if response.status_code == 200:
                return response

            # ------------------------------------------------
            # Rate limit
            # ------------------------------------------------

            if response.status_code == 429:

                retry_after = response.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = delay * attempt
                else:
                    wait = delay * attempt

                print(
                    f"  HTTP 429 - waiting {wait:.1f}s "
                    f"(attempt {attempt}/{retries})"
                )

                time.sleep(wait)
                continue

            # ------------------------------------------------
            # Server errors
            # ------------------------------------------------

            if response.status_code >= 500:

                wait = delay * attempt

                print(
                    f"  HTTP {response.status_code} - "
                    f"waiting {wait:.1f}s "
                    f"(attempt {attempt}/{retries})"
                )

                time.sleep(wait)
                continue

            # ------------------------------------------------
            # Other HTTP error
            # ------------------------------------------------

            response.raise_for_status()

        except requests.RequestException as exc:

            if attempt == retries:
                raise

            wait = delay * attempt

            print(
                f"  Network error: {exc}"
            )

            print(
                f"  Retrying in {wait:.1f}s..."
            )

            time.sleep(wait)

    raise RuntimeError(
        f"Request failed after {retries} attempts: {url}"
    )


# ============================================================
# ORCID
# ============================================================

def get_orcid_works():

    print("Fetching publications from ORCID...")

    response = request_with_retry(
        ORCID_URL,
        headers=HEADERS,
        timeout=30
    )

    data = response.json()

    print(
        f"ORCID groups found: "
        f"{len(data.get('group', []))}"
    )

    return data


# ============================================================
# DOI
# ============================================================

def get_doi(work):

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

            doi = (
                external_id
                .get("external-id-value", "")
                .strip()
            )

            # Odstraníme případný URL prefix
            doi = doi.replace(
                "https://doi.org/",
                ""
            ).replace(
                "http://doi.org/",
                ""
            ).strip()

            return doi

    return ""


# ============================================================
# PUBMED - PMID
# ============================================================

def get_pmid_from_pubmed(doi):

    if not doi:
        return ""

    print(
        f"  PubMed search: {doi}"
    )

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1
    }

    time.sleep(PUBMED_DELAY)

    response = request_with_retry(
        PUBMED_ESEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    data = response.json()

    ids = (
        data
        .get("esearchresult", {})
        .get("idlist", [])
    )

    if ids:
        return ids[0]

    return ""


# ============================================================
# PUBMED - METADATA
# ============================================================

def get_pubmed_metadata(pmid):

    if not pmid:
        return {}

    print(
        f"  PubMed fetch: {pmid}"
    )

    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml"
    }

    # DŮLEŽITÉ:
    # PubMed má rate limit.
    time.sleep(PUBMED_DELAY)

    response = request_with_retry(
        PUBMED_EFETCH_URL,
        params=params,
        headers=PUBMED_HEADERS,
        timeout=30
    )

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

    # --------------------------------------------------------
    # Title
    # --------------------------------------------------------

    title = art.findtext(
        "ArticleTitle",
        default=""
    )

    # --------------------------------------------------------
    # Journal
    # --------------------------------------------------------

    journal = art.findtext(
        ".//Journal/Title",
        default=""
    )

    # --------------------------------------------------------
    # Year
    # --------------------------------------------------------

    year = art.findtext(
        ".//PubDate/Year",
        default=""
    )

    if not year:

        medline_date = art.findtext(
            ".//PubDate/MedlineDate",
            default=""
        )

        if medline_date:
            year = medline_date[:4]

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    volume = art.findtext(
        ".//JournalIssue/Volume",
        default=""
    )

    # --------------------------------------------------------
    # Issue
    # --------------------------------------------------------

    issue = art.findtext(
        ".//JournalIssue/Issue",
        default=""
    )

    # --------------------------------------------------------
    # Pages
    # --------------------------------------------------------

    pages = art.findtext(
        ".//Pagination/MedlinePgn",
        default=""
    )

    # --------------------------------------------------------
    # Authors
    # --------------------------------------------------------

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

        if not lastname:
            continue

        name = lastname

        if initials:
            name += f" {initials}"

        authors.append(name)

    return {
        "title": title,
        "journal": journal,
        "year": year,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "authors": ", ".join(authors)
    }


# ============================================================
# CROSSREF
# ============================================================

def get_crossref_metadata(doi):

    if not doi:
        return {}

    print(
        f"  Crossref: {doi}"
    )

    url = CROSSREF_URL + doi

    try:

        response = request_with_retry(
            url,
            headers=HEADERS,
            timeout=30,
            retries=3,
            delay=2
        )

        return response.json().get(
            "message",
            {}
        )

    except Exception as exc:

        print(
            f"  WARNING: Crossref failed: {exc}"
        )

        return {}


# ============================================================
# AUTHORS FROM CROSSREF
# ============================================================

def format_crossref_authors(metadata):

    authors = []

    for author in metadata.get(
        "author",
        []
    ):

        family = (
            author.get("family", "")
            .strip()
        )

        given = (
            author.get("given", "")
            .strip()
        )

        if not family:
            continue

        initials = ""

        for part in (
            given
            .replace("-", " ")
            .split()
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
# YEAR FROM CROSSREF
# ============================================================

def get_crossref_year(metadata):

    for key in (
        "published-print",
        "published-online",
        "published",
        "issued"
    ):

        date = metadata.get(
            key,
            {}
        )

        parts = date.get(
            "date-parts",
            []
        )

        if parts and parts[0]:

            year = parts[0][0]

            if year:
                return str(year)

    return ""


# ============================================================
# MAIN
# ============================================================

print()
print("=" * 60)
print("VanharaLab publication updater")
print("=" * 60)
print()


data = get_orcid_works()

publications = []


for group in data.get(
    "group",
    []
):

    summaries = group.get(
        "work-summary",
        []
    )

    if not summaries:
        continue

    work = summaries[0]

    # --------------------------------------------------------
    # ORCID basic metadata
    # --------------------------------------------------------

    title = (
        work
        .get("title", {})
        .get("title", {})
        .get("value", "")
        .strip()
    )

    year = ""

    publication_date = work.get(
        "publication-date"
    )

    if publication_date:

        year = (
            publication_date
            .get("year", {})
            .get("value", "")
        )

    journal = ""

    if work.get(
        "journal-title"
    ):

        journal = (
            work["journal-title"]
            .get("value", "")
            .strip()
        )

    doi = get_doi(work)

    print()
    print("-" * 60)
    print(
        f"Processing: {title}"
    )
    print(
        f"  DOI: {doi or 'none'}"
    )

    # --------------------------------------------------------
    # Crossref
    # --------------------------------------------------------

    crossref = get_crossref_metadata(
        doi
    )

    if crossref:

        crossref_title = (
            crossref
            .get("title", [""])[0]
        )

        if crossref_title:
            title = crossref_title

        if crossref.get(
            "container-title"
        ):

            journal = (
                crossref[
                    "container-title"
                ][0]
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
            or crossref.get(
                "article-number"
            )
            or ""
        )

        authors = (
            format_crossref_authors(
                crossref
            )
        )

        crossref_year = (
            get_crossref_year(
                crossref
            )
        )

        if crossref_year:
            year = crossref_year

    else:

        volume = ""
        issue = ""
        pages = ""
        authors = ""

    # --------------------------------------------------------
    # PubMed
    # --------------------------------------------------------

    pmid = ""

    if doi:

        try:

            pmid = get_pmid_from_pubmed(
                doi
            )

        except Exception as exc:

            print(
                f"  WARNING: PubMed search failed: {exc}"
            )

    if pmid:

        try:

            pubmed = get_pubmed_metadata(
                pmid
            )

            # PubMed je autoritativnější pro
            # bibliografická data, pokud je má.

            if pubmed.get(
                "title"
            ):
                title = pubmed["title"]

            if pubmed.get(
                "journal"
            ):
                journal = pubmed["journal"]

            if pubmed.get(
                "year"
            ):
                year = pubmed["year"]

            if pubmed.get(
                "volume"
            ):
                volume = pubmed["volume"]

            if pubmed.get(
                "issue"
            ):
                issue = pubmed["issue"]

            if pubmed.get(
                "pages"
            ):
                pages = pubmed["pages"]

            if pubmed.get(
                "authors"
            ):
                authors = pubmed["authors"]

        except Exception as exc:

            # ------------------------------------------------
            # PUBMED ERROR NESMÍ ZASTAVIT CELÝ BUILD
            # ------------------------------------------------

            print(
                f"  WARNING: PubMed metadata failed: {exc}"
            )

            print(
                "  Continuing with ORCID/Crossref data."
            )

    # --------------------------------------------------------
    # Publication
    # --------------------------------------------------------

    publications.append(
        {
            "year": str(year),
            "title": title,
            "authors": authors,
            "journal": journal,
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "doi": doi,
            "pmid": pmid
        }
    )

    print(
        f"  OK: {title}"
    )


# ============================================================
# REMOVE DUPLICATES
# ============================================================

unique = {}

for publication in publications:

    doi = publication.get(
        "doi",
        ""
    ).strip()

    title = publication.get(
        "title",
        ""
    ).strip()

    if doi:

        key = (
            "doi:"
            + doi.lower()
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


# ============================================================
# SORT
# ============================================================

publications.sort(
    key=lambda x: (
        int(x["year"])
        if str(x["year"]).isdigit()
        else 0
    ),
    reverse=True
)


# ============================================================
# SAVE
# ============================================================

OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True
)

with open(
    OUTPUT,
    "w",
    encoding="utf-8"
) as file:

    yaml.safe_dump(
        publications,
        file,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False
    )


print()
print("=" * 60)
print(
    f"Updated {len(publications)} publications"
)
print(
    f"Saved to: {OUTPUT}"
)
print("=" * 60)
