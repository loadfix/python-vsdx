"""``Hyperlink`` / ``HyperlinkCollection`` proxies — shape hyperlinks.

Visio exposes "hyperlinks" (Insert → Hyperlink in the desktop UI) on
every shape via a ``<Section N="Hyperlink">`` on the shape's own XML.
Each ``<Row>`` inside the section represents one hyperlink. The row's
``@N`` attribute is the hyperlink's programmatic name (Visio desktop
derives it from the hyperlink's label, falling back to ``Row_1`` etc.);
the inner ``<Cell>`` children carry the hyperlink's fields:

* ``<Cell N="Address" V="…">`` — the URL / UNC path / file path. For
  web links this is an http(s) URL; for intra-document jumps it's
  typically empty and ``SubAddress`` carries the target page.
* ``<Cell N="SubAddress" V="…">`` — anchor / page / named-location
  within *Address*. For a Visio intra-document hyperlink this is the
  target page's ``@NameU`` (or ``PageName/ShapeName``).
* ``<Cell N="Description" V="…">`` — user-visible description shown
  in the Hyperlinks pane / tooltip.
* ``<Cell N="ExtraInfo" V="…">`` — query-string / parameter payload
  passed to the target (opaque string, passed verbatim).
* ``<Cell N="NewWindow" V="0|1">`` — open target in a new window.
* ``<Cell N="Default" V="0|1">`` — whether this hyperlink is the
  shape's *default* — the one Visio auto-follows on ctrl-click.
  At most one hyperlink per shape can carry ``Default=1`` (the proxy
  enforces this on write).
* ``<Cell N="Invisible" V="0|1">`` — hide from the Insert Hyperlink
  dialog / right-click menu.
* ``<Cell N="SortKey" V="…">`` — opaque sort-order hint (Visio desktop
  uses it to order the Hyperlinks pane; callers rarely set it).

Design notes (matches the R4-12 geometry + R8-3 shape-data playbook):

- **Zero new ``CT_*`` classes.** Hyperlink rides on the existing
  :class:`~vsdx.oxml.section.CT_Section` /
  :class:`~vsdx.oxml.row.CT_Row` / :class:`~vsdx.oxml.cell.CT_Cell`
  trio. Discrimination is value-level (``section.@N == "Hyperlink"``
  + ``row.@N`` for the hyperlink name), not class-level.
- Collection is **list-like + description-keyed** — ``shape.hyperlinks[0]``
  indexes in document order, ``shape.hyperlinks["Support site"]``
  looks up by ``Description`` (the closest thing Visio has to a
  user-visible identifier, since ``@N`` is often auto-generated).
- :meth:`HyperlinkCollection.add` appends a new ``<Row>`` and returns
  its proxy. Marking an existing hyperlink ``default=True`` auto-
  clears ``Default`` on every sibling so the one-default invariant
  is preserved.

Document-level ``HyperlinkBase`` lives on
:attr:`~vsdx.document.VisioDocument.hyperlink_base` — see the
DocumentSheet ``<Cell N="HyperlinkBase">`` cell.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, List, Optional, Union
from urllib.parse import quote

from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_Row, CT_Section  # TODO(vsdx/track-1)
    from vsdx.shapes.base import Shape


__all__ = [
    "Hyperlink",
    "HyperlinkCollection",
    "build_aws_console_url",
    "build_confluence_url",
    "build_github_url",
    "build_jira_url",
]


_SECTION_NAME = "Hyperlink"


# ---------------------------------------------------------------------------
# Cell-level helpers — named cells inside a <Row>
#
# Duplicated from vsdx.shape_data rather than imported: that module's
# copies are underscore-prefixed (private) and their signatures match
# 1:1. Keeping them local to this file lets the two modules evolve
# independently without a cross-module rename ricochet.
# ---------------------------------------------------------------------------


def _row_cell(row: "CT_Row", name: str) -> Optional["CT_Cell"]:
    """Return the ``<Cell N=name>`` child on *row*, or ``None``."""
    for cell in row.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _get_or_add_row_cell(row: "CT_Row", name: str) -> "CT_Cell":
    """Return ``<Cell N=name>`` on *row*, creating it if absent."""
    cell = _row_cell(row, name)
    if cell is not None:
        return cell
    cell = row._add_cell()
    cell.set("N", name)
    return cell


def _cell_v(row: "CT_Row", name: str) -> Optional[str]:
    """Return ``@V`` on ``<Cell N=name>`` of *row*, or ``None`` if absent."""
    cell = _row_cell(row, name)
    if cell is None:
        return None
    return cell.get("V")


def _set_cell_v(row: "CT_Row", name: str, value: Optional[str]) -> None:
    """Create-or-update ``<Cell N=name V=value>`` on *row*.

    Passing ``None`` clears ``@V`` but leaves the cell element in place
    for round-trip fidelity.
    """
    cell = _get_or_add_row_cell(row, name)
    if value is None:
        cell.attrib.pop("V", None)
        return
    cell.set("V", value)


def _parse_bool(raw: Optional[str]) -> bool:
    """Coerce a Visio boolean ``@V`` to Python ``bool``.

    Visio emits ``"0"``/``"1"`` but tolerates ``TRUE``/``FALSE`` in
    some locales; be forgiving on the read side and strict on write.
    """
    if raw is None:
        return False
    token = raw.strip().lower()
    return token in ("1", "true", "yes", "-1")


# ---------------------------------------------------------------------------
# Hyperlink — one <Row> inside <Section N="Hyperlink">
# ---------------------------------------------------------------------------


class Hyperlink:
    """One hyperlink on a shape.

    Wraps a single ``<Row>`` inside the shape's
    ``<Section N="Hyperlink">``. Callers get these via iteration /
    indexing / lookup on :class:`HyperlinkCollection`; they don't
    construct them directly.

    .. versionadded:: 0.3.0
    """

    def __init__(self, row: "CT_Row", collection: "HyperlinkCollection") -> None:
        self._row = row
        self._collection = collection

    # -- identity -------------------------------------------------------

    @property
    def name(self) -> str:
        """The hyperlink's programmatic name (``Row/@N``).

        Typically ``Row_1`` / ``Row_2`` in Visio-desktop-authored files
        (Visio auto-generates the name from the row ordinal); callers
        may set a more meaningful name via the setter.
        """
        return self._row.get("N") or ""

    @name.setter
    def name(self, value: str) -> None:
        self._row.set("N", str(value))

    @property
    def element(self) -> "CT_Row":
        """The underlying ``<Row>`` element (escape hatch)."""
        return self._row

    # -- content cells --------------------------------------------------

    @property
    def address(self) -> Optional[str]:
        """The target URL / UNC / file path (``<Cell N="Address">``).

        Empty / ``None`` for intra-document jumps — those carry only
        :attr:`sub_address`.
        """
        return _cell_v(self._row, "Address")

    @address.setter
    def address(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "Address", value)

    @property
    def sub_address(self) -> Optional[str]:
        """The anchor / target inside *Address* (``<Cell N="SubAddress">``).

        For intra-document Visio hyperlinks this is the target page's
        ``@NameU`` (optionally followed by ``/ShapeName``).
        """
        return _cell_v(self._row, "SubAddress")

    @sub_address.setter
    def sub_address(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "SubAddress", value)

    @property
    def description(self) -> Optional[str]:
        """User-visible description (``<Cell N="Description">``)."""
        return _cell_v(self._row, "Description")

    @description.setter
    def description(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "Description", value)

    @property
    def extra_info(self) -> Optional[str]:
        """Query-string / parameter payload (``<Cell N="ExtraInfo">``)."""
        return _cell_v(self._row, "ExtraInfo")

    @extra_info.setter
    def extra_info(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "ExtraInfo", value)

    # -- flag cells -----------------------------------------------------

    @property
    def new_window(self) -> bool:
        """Whether to open *Address* in a new window (``<Cell N="NewWindow">``)."""
        return _parse_bool(_cell_v(self._row, "NewWindow"))

    @new_window.setter
    def new_window(self, value: bool) -> None:
        _set_cell_v(self._row, "NewWindow", "1" if value else "0")

    @property
    def default(self) -> bool:
        """Whether this is the shape's default (auto-followed) hyperlink.

        At most one hyperlink per shape can carry ``Default=1``. Setting
        this property to ``True`` automatically clears ``Default`` on
        every sibling, preserving the one-default invariant. Setting
        ``False`` simply clears the flag on this row; the shape may
        then have no default, which Visio tolerates.
        """
        return _parse_bool(_cell_v(self._row, "Default"))

    @default.setter
    def default(self, value: bool) -> None:
        if value:
            # Clear Default on every sibling first, then set on self.
            for row in self._collection._rows():
                if row is self._row:
                    continue
                if _cell_v(row, "Default") not in (None, "0"):
                    _set_cell_v(row, "Default", "0")
            _set_cell_v(self._row, "Default", "1")
        else:
            _set_cell_v(self._row, "Default", "0")

    @property
    def invisible(self) -> bool:
        """Whether the hyperlink is hidden from menus (``<Cell N="Invisible">``)."""
        return _parse_bool(_cell_v(self._row, "Invisible"))

    @invisible.setter
    def invisible(self, value: bool) -> None:
        _set_cell_v(self._row, "Invisible", "1" if value else "0")

    # -- sort-key -------------------------------------------------------

    @property
    def sort_key(self) -> Optional[str]:
        """Sort-order hint (``<Cell N="SortKey">`` ``@V``)."""
        return _cell_v(self._row, "SortKey")

    @sort_key.setter
    def sort_key(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "SortKey", value)

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        parts = [f"name={self.name!r}"]
        if self.description:
            parts.append(f"description={self.description!r}")
        if self.address:
            parts.append(f"address={self.address!r}")
        if self.sub_address:
            parts.append(f"sub_address={self.sub_address!r}")
        if self.default:
            parts.append("default=True")
        return f"<Hyperlink {' '.join(parts)}>"


# ---------------------------------------------------------------------------
# HyperlinkCollection — list-like + by-description lookup
# ---------------------------------------------------------------------------


class HyperlinkCollection(ParentedElementProxy):
    """Shape-scoped hyperlink collection.

    List-like wrapper over the shape's ``<Section N="Hyperlink">``:
    ``shape.hyperlinks[0]`` indexes in document order;
    ``shape.hyperlinks["Support site"]`` looks up by ``Description``
    (raises :class:`KeyError` when no hyperlink carries that
    description).

    Iteration yields :class:`Hyperlink` proxies in document order.
    Missing Hyperlink section behaves as an empty collection — only
    :meth:`add` materialises the section on demand.

    .. versionadded:: 0.3.0
    """

    def __init__(self, shape: "Shape") -> None:
        super().__init__(shape._element, shape)
        self._shape = shape

    # -- section lookup -------------------------------------------------

    def _section(self) -> Optional["CT_Section"]:
        """Return the shape's first ``<Section N="Hyperlink">``, or ``None``."""
        for section in self._shape._element.section_lst:
            if section.get("N") == _SECTION_NAME:
                return section
        return None

    def _get_or_add_section(self) -> "CT_Section":
        """Return the Hyperlink section, creating one if absent."""
        section = self._section()
        if section is not None:
            return section
        section = self._shape._element._add_section()
        section.set("N", _SECTION_NAME)
        return section

    # -- Sequence / lookup surface --------------------------------------

    def _rows(self) -> "List[CT_Row]":
        section = self._section()
        if section is None:
            return []
        return list(section.row_lst)

    def _row_by_description(self, description: str) -> Optional["CT_Row"]:
        for row in self._rows():
            if _cell_v(row, "Description") == description:
                return row
        return None

    def __len__(self) -> int:
        return len(self._rows())

    def __iter__(self) -> Iterator[Hyperlink]:
        for row in self._rows():
            yield Hyperlink(row, self)

    def __getitem__(self, key: Union[int, str]) -> Hyperlink:
        """Index by position (``int``) or lookup by description (``str``).

        :raises IndexError: On out-of-range integer index.
        :raises KeyError: On string key that no hyperlink's
          ``Description`` cell matches.
        """
        rows = self._rows()
        if isinstance(key, int):
            # Supports negative indices like a regular list.
            return Hyperlink(rows[key], self)
        if isinstance(key, str):
            row = self._row_by_description(key)
            if row is None:
                raise KeyError(key)
            return Hyperlink(row, self)
        raise TypeError(
            "HyperlinkCollection indices must be int or str, got %s"
            % type(key).__name__
        )

    def __contains__(self, key: object) -> bool:
        """True when *key* names a hyperlink by description.

        String-only membership: indexing by integer is always valid
        (``x in seq`` semantics for lists already differ from ``x[i]``);
        restricting ``in`` to descriptions matches the dict-like half
        of the collection's surface.
        """
        if not isinstance(key, str):
            return False
        return self._row_by_description(key) is not None

    # -- typed accessors ------------------------------------------------

    def get(
        self, description: str, default: Optional[Hyperlink] = None
    ) -> Optional[Hyperlink]:
        """Return the hyperlink with *description*, or *default*."""
        row = self._row_by_description(description)
        if row is None:
            return default
        return Hyperlink(row, self)

    @property
    def default_hyperlink(self) -> Optional[Hyperlink]:
        """The hyperlink marked ``Default=1``, or ``None`` when none is.

        Visio auto-clicks the default hyperlink on ``Ctrl+Click``. At
        most one hyperlink per shape should carry the flag; if multiple
        somehow do (malformed input), this returns the first in
        document order.
        """
        for row in self._rows():
            if _parse_bool(_cell_v(row, "Default")):
                return Hyperlink(row, self)
        return None

    # -- mutation -------------------------------------------------------

    def add(
        self,
        address: Optional[str] = None,
        *,
        description: Optional[str] = None,
        sub_address: Optional[str] = None,
        extra_info: Optional[str] = None,
        new_window: bool = False,
        default: bool = False,
        invisible: bool = False,
        sort_key: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Hyperlink:
        """Append a new hyperlink and return its proxy.

        The new ``<Row>`` is emitted into the shape's
        ``<Section N="Hyperlink">`` (materialised on first use).

        :param address: Target URL / UNC / file path. May be ``None``
          for intra-document jumps (only *sub_address* carries the
          target in that case).
        :param description: User-visible description (hyperlink label).
        :param sub_address: Anchor / target inside *address*.
        :param extra_info: Query-string / parameter payload.
        :param new_window: Open *address* in a new window.
        :param default: Mark this hyperlink as the shape's default
          (auto-followed on ctrl-click). Clears ``Default`` on every
          sibling to preserve the one-default invariant.
        :param invisible: Hide from menus / Hyperlinks pane.
        :param sort_key: Opaque sort-order hint.
        :param name: Programmatic name (``Row/@N``). Defaults to
          ``Row_<ordinal>`` matching Visio desktop's auto-naming.
        :returns: The :class:`Hyperlink` proxy for the new row.

        .. versionadded:: 0.3.0
        """
        section = self._get_or_add_section()
        row = section._add_row()
        # Compute the default name from the row's 1-based ordinal in
        # the section. Visio uses ``Row_<n>`` where <n> is the IX-like
        # index; we count after adding so the count reflects the new
        # row's position.
        ordinal = len(section.row_lst)
        row.set("N", name if name is not None else f"Row_{ordinal}")
        hyperlink = Hyperlink(row, self)
        # Cell emission order matches Visio desktop's canonical order:
        # Description, Address, SubAddress, ExtraInfo, SortKey,
        # NewWindow, Default, Invisible. We only write cells the caller
        # supplied — Visio tolerates absent cells (default to empty
        # string / false) and omitting them keeps add-then-save XML
        # byte-identical to hand-authored files.
        if description is not None:
            hyperlink.description = description
        if address is not None:
            hyperlink.address = address
        if sub_address is not None:
            hyperlink.sub_address = sub_address
        if extra_info is not None:
            hyperlink.extra_info = extra_info
        if sort_key is not None:
            hyperlink.sort_key = sort_key
        if new_window:
            hyperlink.new_window = True
        # Default has tri-state semantics on write: True marks + clears
        # siblings; False with other siblings still present needs the
        # explicit "0" cell so a caller switching from default-on to
        # default-off round-trips cleanly. On the first row no cell is
        # needed (absent == false).
        if default:
            hyperlink.default = True
        if invisible:
            hyperlink.invisible = True
        return hyperlink

    def remove(self, key: Union[int, str, Hyperlink]) -> None:
        """Remove a hyperlink by position, description, or proxy.

        :param key: Integer index into the collection, a string matched
          against the ``Description`` cell, or a :class:`Hyperlink`
          proxy (same row element identity).
        :raises IndexError: On out-of-range integer index.
        :raises KeyError: On string key that no description matches.
        :raises ValueError: On a :class:`Hyperlink` that isn't in this
          collection.

        Leaves the ``<Section N="Hyperlink">`` in place even when the
        last row is removed — Visio tolerates empty sections and
        preserving the element keeps byte-identity on round-trips that
        touch a hyperlink the caller then adds back.

        .. versionadded:: 0.3.0
        """
        section = self._section()
        if section is None:
            # No section — every remove is a miss.
            if isinstance(key, int):
                raise IndexError(key)
            if isinstance(key, str):
                raise KeyError(key)
            raise ValueError("hyperlink not in collection")
        if isinstance(key, Hyperlink):
            target = key._row
            if target.getparent() is not section:
                raise ValueError("hyperlink not in this collection")
            section.remove(target)
            return
        if isinstance(key, int):
            rows = list(section.row_lst)
            target = rows[key]  # Propagates IndexError on OOB.
            section.remove(target)
            return
        if isinstance(key, str):
            target = self._row_by_description(key)
            if target is None:
                raise KeyError(key)
            section.remove(target)
            return
        raise TypeError(
            "HyperlinkCollection.remove takes int / str / Hyperlink, got %s"
            % type(key).__name__
        )

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        descs = []
        for row in self._rows():
            d = _cell_v(row, "Description")
            descs.append(repr(d) if d else repr(row.get("N") or ""))
        return f"<HyperlinkCollection [{', '.join(descs)}]>"


# ---------------------------------------------------------------------------
# URL pattern builders — public helpers consumed by Shape.link_to_*
#
# These produce the canonical web-console URL for the given service/
# resource combo. Kept module-level (rather than baked into Shape) so
# callers writing ad-hoc tooling can reuse them without going through
# a Shape proxy:
#
#     >>> from vsdx.hyperlinks import build_aws_console_url
#     >>> build_aws_console_url(service="ec2", resource_id="i-abc",
#     ...                       region="ap-southeast-2")
#     'https://ap-southeast-2.console.aws.amazon.com/ec2/home?region=ap-southeast-2#Instances:instanceId=i-abc'
#
# The builders aim for "URL that opens the resource's detail page when
# pasted into a browser logged into the right account / instance".
# Service-specific deep-link patterns are best-effort — AWS / Atlassian
# console URL formats drift over time. When a console reorganises,
# update the builder rather than asking callers to construct the URL.
#
# .. versionadded:: 0.3.0
# ---------------------------------------------------------------------------


# AWS service code → (deep-link path template, resource fragment template).
# Keyed on the service code Visio diagrams typically carry (matches the
# ``service=`` kwarg on :meth:`Shape.link_to_aws_console`). Unmapped
# services fall back to the service home page (no resource deep link).
_AWS_DEEP_LINKS = {
    # service: (path, fragment with {id})
    "ec2": ("ec2/home", "Instances:instanceId={id}"),
    "s3": ("s3/buckets/{id}", ""),
    "lambda": ("lambda/home", "/functions/{id}"),
    "rds": ("rds/home", "database:id={id};is-cluster=false"),
    "dynamodb": ("dynamodb/home", "tables:selected={id}"),
    "iam": ("iam/home", "/users/{id}"),
    "vpc": ("vpc/home", "vpcs:VpcId={id}"),
    "cloudwatch": ("cloudwatch/home", "logsV2:log-groups/log-group/{id}"),
    "sqs": ("sqs/v2/home", "/queues/{id}"),
    "sns": ("sns/v3/home", "/topic/{id}"),
}


def build_aws_console_url(
    *,
    service: str,
    resource_id: Optional[str] = None,
    region: Optional[str] = None,
) -> str:
    """Build an AWS console URL for *service* (and optionally a resource).

    :param service: AWS service code — ``"ec2"``, ``"s3"``, ``"lambda"``,
      ``"rds"``, ``"dynamodb"``, ``"iam"``, ``"vpc"``, ``"cloudwatch"``,
      ``"sqs"``, ``"sns"``. Unknown services fall back to a generic
      ``console.aws.amazon.com/<service>`` link with no resource deep
      link.
    :param resource_id: Optional resource identifier (instance-id /
      bucket-name / function-name / table-name / ...). When supplied,
      the URL navigates to the resource's detail page where AWS supports
      it.
    :param region: Optional AWS region (``"ap-southeast-2"`` etc). When
      supplied the URL is prefixed with the regional console host
      and a ``?region=`` query parameter; service home defaults to the
      account's "last used" region otherwise.
    :returns: A console URL safe to paste into a browser.

    .. versionadded:: 0.3.0
    """
    host = (
        f"{region}.console.aws.amazon.com"
        if region
        else "console.aws.amazon.com"
    )
    spec = _AWS_DEEP_LINKS.get(service.lower())
    if spec is None:
        # Unknown service: link to the service's home page.
        return f"https://{host}/{service.lower()}/home" + (
            f"?region={region}" if region else ""
        )
    path_template, fragment_template = spec
    if resource_id is None or fragment_template == "":
        # Either no resource deep link supported, or caller didn't pass
        # one — fold the id into the path template (S3 buckets) or omit
        # the fragment entirely.
        path = path_template.format(id=resource_id or "")
        url = f"https://{host}/{path}"
        if region:
            url += f"?region={region}"
        return url
    path = path_template
    fragment = fragment_template.format(id=resource_id)
    url = f"https://{host}/{path}"
    if region:
        url += f"?region={region}"
    url += f"#{fragment}"
    return url


def build_github_url(
    *,
    repo: str,
    file: Optional[str] = None,
    line: Optional[int] = None,
    branch: str = "main",
) -> str:
    """Build a github.com URL for *repo* (and optionally a file / line).

    :param repo: ``"owner/repo"`` slug.
    :param file: Optional path within the repo (``"src/main.py"``).
      When omitted, the URL points at the repository root.
    :param line: Optional 1-based line number. Ignored when *file* is
      ``None``.
    :param branch: Branch / ref to link against. Defaults to ``"main"``
      since GitHub renamed master → main in 2020 and the AWS / k8s /
      most modern repos honour the new default. Override for older
      repos that still use ``"master"`` or for tag / SHA links.
    :returns: A canonical github.com URL.

    .. versionadded:: 0.3.0
    """
    base = f"https://github.com/{repo}"
    if file is None:
        return base
    # GitHub URL form: /<owner>/<repo>/blob/<ref>/<path>[#L<line>]
    url = f"{base}/blob/{branch}/{file.lstrip('/')}"
    if line is not None:
        url += f"#L{int(line)}"
    return url


def build_confluence_url(
    *,
    base_url: str,
    space: str,
    page: str,
) -> str:
    """Build a Confluence page URL.

    :param base_url: Confluence site URL — ``"https://acme.atlassian.net/wiki"``
      for Atlassian Cloud, ``"https://confluence.example.com"`` for
      self-hosted Server / Data Center. Trailing slash is tolerated.
    :param space: Space key (``"ENG"``, ``"DOCS"``, ...).
    :param page: Page title. Spaces are URL-encoded.
    :returns: A Confluence page URL using the ``display`` view path
      that resolves both Atlassian Cloud and Server.

    .. versionadded:: 0.3.0
    """
    base = base_url.rstrip("/")
    encoded_page = quote(page, safe="")
    return f"{base}/display/{space}/{encoded_page}"


def build_jira_url(
    *,
    base_url: str,
    project: str,
    issue: Union[int, str],
) -> str:
    """Build a Jira issue URL.

    :param base_url: Jira site URL — ``"https://acme.atlassian.net"``
      for Atlassian Cloud, ``"https://jira.example.com"`` for
      self-hosted Server / Data Center. Trailing slash is tolerated.
    :param project: Project key (``"ABC"``, ``"PROJ"``, ...).
    :param issue: Issue number (``123``) or full key (``"ABC-123"``).
      Numbers are joined to *project* with ``"-"``; pre-formatted keys
      pass through verbatim so the helper accepts both forms callers
      might already have on hand.
    :returns: A Jira issue URL of the form
      ``<base_url>/browse/<PROJECT>-<NUMBER>``.

    .. versionadded:: 0.3.0
    """
    base = base_url.rstrip("/")
    if isinstance(issue, int):
        key = f"{project}-{issue}"
    else:
        # Allow callers to pass a full key (``"ABC-123"``) or a bare
        # numeric string (``"123"``).
        key = issue if "-" in issue else f"{project}-{issue}"
    return f"{base}/browse/{key}"
