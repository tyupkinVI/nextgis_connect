import platform
from enum import Enum, auto
from itertools import islice
from pathlib import Path
import re
from typing import Any, Optional, Tuple, Union, cast

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsSettings,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import (
    QByteArray,
    QLocale,
    QMimeData,
    QSize,
    Qt,
    QVariant,
)
from qgis.PyQt.QtGui import QClipboard, QIcon, QPainter, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
)
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

from nextgis_connect.compat import QGIS_3_30
from nextgis_connect.core.ui.about_dialog import AboutDialog
from nextgis_connect.settings.ng_connect_settings import NgConnectSettings

iface = cast(QgisInterface, iface)


class SupportStatus(Enum):
    OLD_NGW = auto()
    OLD_CONNECT = auto()
    SUPPORTED = auto()


class ChooserDialog(QDialog):
    def __init__(self, options):
        super().__init__()
        self.options = options

        self.setLayout(QVBoxLayout())

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.list.setSelectionBehavior(
            QListWidget.SelectionBehavior.SelectItems
        )
        self.layout().addWidget(self.list)

        for option in options:
            item = QListWidgetItem(option)
            self.list.addItem(item)

        self.list.setCurrentRow(0)

        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok, Qt.Orientation.Horizontal, self
        )
        ok_button = self.btn_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_button is not None
        ok_button.clicked.connect(self.accept)
        self.layout().addWidget(self.btn_box)

        self.seleced_options = []

    def accept(self):
        self.seleced_options = [
            item.text() for item in self.list.selectedItems()
        ]
        super().accept()


def open_plugin_help():
    dialog = AboutDialog(str(Path(__file__).parent.name))
    dialog.exec()


def set_clipboard_data(
    mime_type: str, data: Union[QByteArray, bytes, bytearray], text: str
):
    mime_data = QMimeData()
    mime_data.setData(mime_type, data)
    if len(text) > 0:
        mime_data.setText(text)

    clipboard = QgsApplication.clipboard()
    assert clipboard is not None
    if platform.system() == "Linux":
        selection_mode = QClipboard.Mode.Selection
        clipboard.setMimeData(mime_data, selection_mode)
    clipboard.setMimeData(mime_data, QClipboard.Mode.Clipboard)


def is_version_supported(current_version_string: str) -> SupportStatus:
    def version_to_tuple(version: str) -> Tuple[int, int]:
        minor, major = islice(map(int, version.split(".")), 2)
        return minor, major

    def version_shift(version: Tuple[int, int], shift: int) -> Tuple[int, int]:
        version_number = version[0] * 10 + version[1]
        shifted_version = version_number + shift
        return shifted_version // 10, shifted_version % 10

    current_version = version_to_tuple(current_version_string)

    settings = NgConnectSettings()
    if settings.is_developer_mode:
        return SupportStatus.SUPPORTED

    supported_version_string = settings.supported_ngw_version
    supported_version = version_to_tuple(supported_version_string)

    oldest_version = version_shift(supported_version, -2)
    newest_version = version_shift(supported_version, 1)

    if current_version < oldest_version:
        return SupportStatus.OLD_NGW

    if current_version > newest_version:
        return SupportStatus.OLD_CONNECT

    return SupportStatus.SUPPORTED


def get_project_import_export_menu() -> Optional[QMenu]:
    """
    Returns the application Project - Import/Export sub menu
    """
    if Qgis.versionInt() >= QGIS_3_30:
        return iface.projectImportExportMenu()

    project_menu = iface.projectMenu()
    matches = [
        m
        for m in project_menu.children()
        if m.objectName() == "menuImport_Export"
    ]
    if matches:
        return matches[0]

    return None


def add_project_export_action(project_export_action: QAction) -> None:
    """
    Decides how to add action of project export to the Project - Import/Export sub menu
    """
    if Qgis.versionInt() >= QGIS_3_30:
        iface.addProjectExportAction(project_export_action)
    else:
        import_export_menu = get_project_import_export_menu()
        if import_export_menu:
            export_separators = [
                action
                for action in import_export_menu.actions()
                if action.isSeparator()
            ]
            if export_separators:
                import_export_menu.insertAction(
                    export_separators[0],
                    project_export_action,
                )
            else:
                import_export_menu.addAction(project_export_action)


def locale() -> str:
    override_locale = QgsSettings().value(
        "locale/overrideFlag", defaultValue=False, type=bool
    )
    if not override_locale:
        locale_full_name = QLocale.system().name()
    else:
        locale_full_name = QgsSettings().value("locale/userLocale", "")
    locale = locale_full_name[0:2].lower()
    return locale


def nextgis_domain(subdomain: Optional[str] = None) -> str:
    speaks_russian = locale() in ["be", "kk", "ky", "ru", "uk"]
    if subdomain is None:
        subdomain = ""
    elif not subdomain.endswith("."):
        subdomain += "."
    return f"https://{subdomain}nextgis.{'ru' if speaks_russian else 'com'}"


def utm_tags(utm_medium: str, *, utm_campaign: str = "constant") -> str:
    utm = (
        f"utm_source=qgis_plugin&utm_medium={utm_medium}"
        f"&utm_campaign={utm_campaign}&utm_term=nextgis_connect"
        f"&utm_content={locale()}"
    )
    return utm


def wrap_sql_value(value: Any) -> str:
    """
    Converts a Python value to a SQL-compatible string representation.

    :param value: The value to be converted.
    :type value: Any
    :return: The SQL-compatible string representation of the value.
    :rtype: str
    """
    if isinstance(value, str):
        value = value.replace("'", r"''")
        return f"'{value}'"
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "NULL"
    return str(value)


def wrap_sql_table_name(value: Any) -> str:
    """
    Wraps a given value in double quotes for use as an SQL table name,
    escaping any existing double quotes within the value.

    :param value: The value to be wrapped.
    :type value: Any
    :return: The value wrapped in double quotes.
    :rtype: str
    """
    value = value.replace('"', r'""')
    return f'"{value}"'


def draw_icon(label: QLabel, icon: QIcon, *, size: int = 24) -> None:
    pixmap = icon.pixmap(icon.actualSize(QSize(size, size)))
    label.setPixmap(pixmap)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)


def material_icon(
    name: str, *, color: str = "", size: Optional[int] = None
) -> QIcon:
    name = f"{name}.svg" if not name.endswith(".svg") else name
    svg_path = Path(__file__).parent / "icons" / "material" / name

    if not svg_path.exists():
        raise FileNotFoundError(f"SVG file not found: {svg_path}")

    with open(svg_path, encoding="utf-8") as file:
        svg_content = file.read()

    if color == "":
        color = QgsApplication.palette().text().color().name()

    modified_svg = svg_content.replace('fill="#ffffff"', f'fill="{color}"')

    byte_array = QByteArray(modified_svg.encode("utf-8"))
    renderer = QSvgRenderer()
    if not renderer.load(byte_array):
        raise ValueError("Failed to render modified SVG.")

    pixmap = QPixmap(
        renderer.defaultSize() if size is None else QSize(size, size)
    )
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)


# Workaround class for NGW issues with boolean fields in style expressions.
class NGWQMLProcessor:
    def __init__(self, qml_xml_string: str, qgs_map_layer):
        self.qml = qml_xml_string
        self.layer = qgs_map_layer
        self.has_change = False

        self.doc = QDomDocument()
        self.doc.setContent(qml_xml_string)

        self.bool_fields_name: list[str] = [
            field.name()
            for field in self.layer.fields()
            if field is not None and field.type() == QVariant.Bool
        ]

        self.pk_field_name = ""
        self.need_check_pk = self.layer.providerType() == "ogr"
        pk_attrs_indicies = self.layer.primaryKeyAttributes()
        if self.need_check_pk and len(pk_attrs_indicies):
            pk_field = self.layer.fields()[pk_attrs_indicies[0]]
            if not pk_field.type() == QVariant.LongLong:
                self.need_check_pk = False
            else:
                self.pk_field_name = pk_field.name()
        else:
            self.need_check_pk = False

    def erase_simple_text(self, expression: str) -> Tuple[str, "list[str]"]:
        parts = []

        def replacer(match):
            parts.append(match.group(0))
            return f"$${len(parts) - 1}$$"

        expression = re.sub(r"'[^']*'", replacer, expression)
        return expression, parts

    def restore_simple_text(self, expression: str, parts: "list[str]") -> str:
        for i, part in enumerate(parts):
            expression = expression.replace(f"$${i}$$", part, 1)
        return expression

    def process_label(self) -> None:
        labeling_nodes = self.doc.elementsByTagName("text-style")
        for i in range(labeling_nodes.count()):
            labeling_node = labeling_nodes.at(i).toElement()
            if not labeling_node.hasAttribute("fieldName"):
                continue

            label_expression = labeling_node.attribute("fieldName")

            if label_expression == "@id":
                continue

            expression, parts = self.erase_simple_text(label_expression)

            if self.need_check_pk:
                expression, has_change = self.pk_to_id(expression)
                self.has_change = self.has_change or has_change
                if has_change:
                    labeling_node.setAttribute("isExpression", "1")
                    labeling_node.setAttribute("fieldName", expression)

            for field_name in self.bool_fields_name:
                expression, has_change = self.bool_to_int(
                    field_name, expression
                )
                if has_change:
                    labeling_node.setAttribute("isExpression", "1")
                    labeling_node.setAttribute("fieldName", expression)
                    self.has_change = self.has_change or has_change

            expression = self.restore_simple_text(expression, parts)

    def process_rules(self, renderer_node: QDomDocument) -> None:
        rules_nodes = renderer_node.elementsByTagName("rules")
        if rules_nodes.count() == 0:
            return

        rules_node = rules_nodes.at(0).toElement()
        rule_nodes = rules_node.elementsByTagName("rule")
        for j in range(rule_nodes.count()):
            rule_node = rule_nodes.at(j).toElement()
            filter_expr = rule_node.attribute("filter")
            if not filter_expr:
                continue

            if not self.need_check_pk:
                continue

            expression, parts = self.erase_simple_text(filter_expr)
            expression, has_change = self.pk_to_id(expression)
            self.has_change = self.has_change or has_change
            expression = self.restore_simple_text(expression, parts)

            rule_node.setAttribute("filter", expression)

    def process_categories(self, renderer_node: QDomDocument) -> None:
        categories = renderer_node.elementsByTagName("category")
        for j in range(categories.count()):
            category = categories.at(j).toElement()
            if not category.attribute("type") == "bool":
                continue

            category.setAttribute("type", "integer")
            value = category.attribute("value")
            if value.lower() == "true":
                category.setAttribute("value", "1")
            elif value.lower() == "false":
                category.setAttribute("value", "0")
            self.has_change = True

    def process_user_defines(self) -> None:
        if not self.need_check_pk:
            return

        data_defined_properties = self.doc.elementsByTagName(
            "data_defined_properties"
        )
        for i in range(data_defined_properties.count()):
            data_node = data_defined_properties.at(i).toElement()

            options = data_node.elementsByTagName("Option")
            for j in range(options.count()):
                option = options.at(j).toElement()
                if (
                    not option.hasAttribute("name")
                    or not option.attribute("name") == "expression"
                ):
                    continue

                option_expression = option.attribute("value")

                option_expression, parts = self.erase_simple_text(
                    option_expression
                )
                option_expression, has_change = self.pk_to_id(
                    option_expression
                )
                self.has_change = self.has_change or has_change
                option.setAttribute("value", option_expression)

                option_expression = self.restore_simple_text(
                    option_expression, parts
                )

    def pk_to_id(self, expression: str) -> Tuple[str, bool]:
        pattern = rf'"{re.escape(self.pk_field_name)}"|\b{re.escape(self.pk_field_name)}\b'
        expression, count = re.subn(pattern, "@id", expression)
        return expression, count > 0

    def bool_to_int(
        self, field_name: str, expression: str
    ) -> Tuple[str, bool]:
        pattern = rf'"{re.escape(field_name)}"|\b{re.escape(field_name)}\b'
        label_expression, count = re.subn(
            pattern, f'if("{field_name}", true, false)', expression
        )
        return label_expression, count > 0

    def process(self) -> str:
        renderers = self.doc.elementsByTagName("renderer-v2")
        for i in range(renderers.count()):
            renderer_node = renderers.at(i).toElement()

            if renderer_node.hasAttribute("type"):
                if renderer_node.attribute("type") == "categorizedSymbol":
                    self.process_categories(renderer_node)
                elif renderer_node.attribute("type") == "RuleRenderer":
                    self.process_rules(renderer_node)

            self.process_label()

            self.process_user_defines()

        if not self.has_change:
            return self.qml
        return self.doc.toString()
