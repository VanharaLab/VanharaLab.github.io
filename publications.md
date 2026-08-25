---
layout: page
title: Publications
---

{% assign current_year = "" %}

{% for pub in site.data.publications %}

{% if pub.year != current_year %}

## {{ pub.year }}

{% assign current_year = pub.year %}

{% endif %}

- **{{ pub.title }}**.  
  *{{ pub.journal }}*.
  {% if pub.doi %} [DOI](https://doi.org/{{ pub.doi }}).{% endif %}
  {% if pub.pmid %} [PubMed](https://pubmed.ncbi.nlm.nih.gov/{{ pub.pmid }}/).{% endif %}

{% endfor %}
