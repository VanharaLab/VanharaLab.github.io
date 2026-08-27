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
)

PUBMED_ESEARCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
)

PUBMED_EFETCH_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
)

CROSSREF_URL = "https://api.crossref.org/works/"

# DŮLEŽITÉ:
# NCBI doporučuje uvádět tool a email.
# Pokud chceš, můžeš zde později doplnit svůj skutečný email.
NCBI_TOOL = "VanharaLabPublications"
NCBI_EMAIL = "vanharalab@example.com"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "VanharaLabPublications/1.0"
}

# ORCID načítáme po 100 záznamech.
ORCID_PAGE_SIZE = 100

# Mezi PubMed požadavky malá pauza,
# aby nedošlo k HTTP 429.
PUBMED_DELAY = 0.4


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# ORCID
# ============================================================

def get_orcid_works():

    print()
    print("=" * 70)
    print("FETCHING WORKS FROM ORCID")
    print("=" * 70)

    all_groups = []

    start = 0

    while True:

        params = {
            "start": start,
            "rows": ORCID_PAGE_SIZE
        }

        print(
            f"ORCID request: start={start}, "
            f"rows={ORCID_PAGE_SIZE}"
        )

        response = session.get(
            ORCID_URL,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        groups = data.get(
            "group",
            []
        )

        if not groups:
            break

        all_groups.extend(groups)

        print(
            f"  received: {len(groups)}"
        )

        print(
            f"  total so far: {len(all_groups)}"
        )

        if len(groups) < ORCID_PAGE_SIZE:
            break

        start += ORCID_PAGE_SIZE

    print()
    print(
        f"ORCID TOTAL WORK GROUPS: {len(all_groups)}"
    )

    return all_groups


# ============================================================
# ORCID TITLE
# ============================================================

def get_orcid_title(work):

    return (
        work
        .get("title", {})
        .get("title", {})
        .get("value", "")
        .strip()
    )


# ============================================================
# ORCID YEAR
# ============================================================

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


# ============================================================
# ORCID JOURNAL
# ============================================================

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


# ============================================================
# ORCID DOI
# ============================================================

def get_orcid_doi(work):

    external_ids = (
        work
        .get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:

        identifier_type = (
            external_id
            .get("external-id-type", "")
            .strip()
            .lower()
        )

        if identifier_type == "doi":

            value = (
                external_id
                .get("external-id-value", "")
                .strip()
            )

            # Odstraníme případný URL prefix.
            value = value.replace(
                "https://doi.org/",
                ""
            )

            value = value.replace(
                "http://doi.org/",
                ""
            )

            value = value.replace(
                "doi:",
                ""
            )

            return value.strip()

    return ""


# ============================================================
# ORCID AUTHORS
# ============================================================

def get_orcid_authors(work):

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
            contributor
            .get("credit-name", {})
            .get("value", "")
        )

        if credit_name:
            authors.append(
                credit_name.strip()
            )

    return ", ".join(authors)


# ============================================================
# CROSSREF
# ============================================================

def get_crossref_metadata(doi):

    if not doi:
        return {}

    try:

        response = session.get(
            CROSSREF_URL + doi,
            timeout=30
        )

        if response.status_code != 200:

            print(
                f"  Crossref unavailable: {doi}"
            )

            return {}

        return response.json().get(
            "message",
            {}
        )

    except requests.RequestException as error:

        print(
            f"  Crossref error: {error}"
        )

        return {}


# ============================================================
# CROSSREF AUTHORS
# ============================================================

def format_crossref_authors(metadata):

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

        for part in given.replace(
            "-",
            " "
        ).split():

            if part:
                initials += (
                    part[0].upper()
                )

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
# PUBMED SEARCH
# ============================================================

def find_pmid_by_doi(doi):

    if not doi:
        return ""

    params = {
        "db": "pubmed",
        "term": f'"{doi}"[doi]',
        "retmode": "json",
        "retmax": 1,
        "tool": NCBI_TOOL,
        "email": NCBI_EMAIL
    }

    try:

        time.sleep(
            PUBMED_DELAY
        )

        response = session.get(
            PUBMED_ESEARCH_URL,
            params=params,
            timeout=30
        )

        if response.status_code == 429:

            print(
                "  PubMed rate limit (429). "
                "Waiting 5 seconds..."
            )

            time.sleep(5)

            response = session.get(
                PUBMED_ESEARCH_URL,
                params=params,
                timeout=30
            )

        response.raise_for_status()

        result = response.json()

        ids = (
            result
            .get("esearchresult", {})
            .get("idlist", [])
        )

        if ids:
            return ids[0]

    except requests.RequestException as error:

        print(
            f"  PubMed search failed: {error}"
        )

    return ""


# ============================================================
# PUBMED METADATA
# ============================================================

def get_pubmed_metadata(pmid):

    if not pmid:
        return {}

    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "tool": NCBI_TOOL,
        "email": NCBI_EMAIL
    }

    try:

        time.sleep(
            PUBMED_DELAY
        )

        response = session.get(
            PUBMED_EFETCH_URL,
            params=params,
            timeout=30
        )

        if response.status_code == 429:

            print(
                "  PubMed rate limit (429). "
                "Waiting 5 seconds..."
            )

            time.sleep(5)

            response = session.get(
                PUBMED_EFETCH_URL,
                params=params,
                timeout=30
            )

        response.raise_for_status()

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

                authors.append(
                    name
                )

        return {
            "title": title.strip(),
            "journal": journal.strip(),
            "year": year.strip(),
            "volume": volume.strip(),
            "issue": issue.strip(),
            "pages": pages.strip(),
            "authors": ", ".join(authors)
        }

    except requests.RequestException as error:

        print(
            f"  PubMed fetch failed: {error}"
        )

    except ET.ParseError as error:

        print(
            f"  PubMed XML error: {error}"
        )

    return {}


# ============================================================
# BUILD ONE PUBLICATION
# ============================================================

def build_publication(work):

    title = get_orcid_title(
        work
    )

    year = get_orcid_year(
        work
    )

    journal = get_orcid_journal(
        work
    )

    doi = get_orcid_doi(
        work
    )

    authors = get_orcid_authors(
        work
    )

    publication = {
        "year": year,
        "title": title,
        "authors": authors,
        "journal": journal,
        "volume": "",
        "issue": "",
        "pages": "",
        "doi": doi,
        "pmid": ""
    }

    # --------------------------------------------------------
    # CROSSREF
    # --------------------------------------------------------

    if doi:

        crossref = get_crossref_metadata(
            doi
        )

        if crossref:

            if crossref.get(
                "title"
            ):

                publication["title"] = (
                    crossref["title"][0]
                )

            if crossref.get(
                "container-title"
            ):

                publication["journal"] = (
                    crossref[
                        "container-title"
                    ][0]
                )

            publication["volume"] = (
                crossref.get(
                    "volume",
                    ""
                )
            )

            publication["issue"] = (
                crossref.get(
                    "issue",
                    ""
                )
            )

            publication["pages"] = (
                crossref.get(
                    "page"
                )
                or crossref.get(
                    "article-number"
                )
                or ""
            )

            crossref_authors = (
                format_crossref_authors(
                    crossref
                )
            )

            if crossref_authors:
                publication["authors"] = (
                    crossref_authors
                )

    # --------------------------------------------------------
    # PUBMED
    # --------------------------------------------------------

    if doi:

        pmid = find_pmid_by_doi(
            doi
        )

        if pmid:

            publication["pmid"] = pmid

            pubmed = get_pubmed_metadata(
                pmid
            )

            if pubmed:

                if pubmed.get(
                    "authors"
                ):
                    publication["authors"] = (
                        pubmed["authors"]
                    )

                if pubmed.get(
                    "journal"
                ):
                    publication["journal"] = (
                        pubmed["journal"]
                    )

                if pubmed.get(
                    "volume"
                ):
                    publication["volume"] = (
                        pubmed["volume"]
                    )

                if pubmed.get(
                    "issue"
                ):
                    publication["issue"] = (
                        pubmed["issue"]
                    )

                if pubmed.get(
                    "pages"
                ):
                    publication["pages"] = (
                        pubmed["pages"]
                    )

    return publication


# ============================================================
# MAIN
# ============================================================

def main():

    groups = get_orcid_works()

    publications = []

    print()
    print("=" * 70)
    print("PROCESSING PUBLICATIONS")
    print("=" * 70)

    for index, group in enumerate(
        groups,
        start=1
    ):

        summaries = group.get(
            "work-summary",
            []
        )

        if not summaries:
            continue

        # ORCID groups can contain several summaries.
        # We process every summary, not just the first one.
        for work in summaries:

            title = get_orcid_title(
                work
            )

            print()
            print(
                f"[{index}/{len(groups)}] {title}"
            )

            publication = (
                build_publication(
                    work
                )
            )

            print(
                f"  DOI: "
                f"{publication['doi'] or 'none'}"
            )

            print(
                f"  PMID: "
                f"{publication['pmid'] or 'none'}"
            )

            publications.append(
                publication
            )

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    unique = {}

    for publication in publications:

        doi = (
            publication["doi"]
            .strip()
            .lower()
        )

        title = (
            publication["title"]
            .strip()
            .lower()
        )

        if doi:

            key = f"doi:{doi}"

        elif title:

            key = f"title:{title}"

        else:

            continue

        unique[key] = publication

    publications = list(
        unique.values()
    )

    # ========================================================
    # SORT
    # ========================================================

    def year_key(publication):

        try:

            return int(
                publication["year"]
            )

        except (
            ValueError,
            TypeError
        ):

            return 0

    publications.sort(
        key=year_key,
        reverse=True
    )

    # ========================================================
    # OUTPUT
    # ========================================================

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

    with open(
        output,
        "w",
        encoding="utf-8"
    ) as file:

        yaml.dump(
            publications,
            file,
            allow_unicode=True,
            sort_keys=False
        )

    # ========================================================
    # FINAL REPORT
    # ========================================================

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)

    print(
        f"ORCID groups:       {len(groups)}"
    )

    print(
        f"Publications saved: {len(publications)}"
    )

    print(
        f"Output file:        {output}"
    )

    # ========================================================
    # SPECIFIC CHECK
    # ========================================================

    target_pmid = "40413286"

    target_doi = (
        "10.1007/s00011-025-02041-4"
    )

    found = False

    for publication in publications:

        if (
            publication["pmid"]
            == target_pmid
            or
            publication["doi"].lower()
            == target_doi.lower()
        ):

            found = True

            print()
            print(
                "TARGET PUBLICATION FOUND:"
            )

            print(
                f"  {publication}"
            )

            break

    if not found:

        print()
        print(
            "WARNING:"
        )

        print(
            "Target publication PMID "
            f"{target_pmid} was NOT found."
        )

        print(
            "This means the problem is "
            "upstream in the ORCID data."
        )


if __name__ == "__main__":
    main()
