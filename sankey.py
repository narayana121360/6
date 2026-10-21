"""
Exergy Sankey diagrams for the five waste heat recovery cycles.

Each cycle's calc() stores its exergy results in `cycle.exergy` (one line
added before calc()'s return). build_flows() turns those into a plain
{labels, sources, targets, values} dict -- JSON-safe, so the IDAES cycles
can send it back from co2_runner.py -- and figure() draws it with Plotly.

All values are exergy rates in kW. The layout follows the "overall" Sankey
diagrams already in steam.py and super.py: exergy input -> cycle -> useful
output, exergy destruction in each component, and exergy lost to the
cooling water.
"""

USEFUL = "#2e7d32"      # useful output
LOSS = "#1e88e5"        # exergy carried away (cooling water, bottoming cycle)
DESTROYED = "#e53935"   # exergy destruction
INPUT = "#fb8c00"       # exergy input
CYCLE = "#546e7a"


def _f(x):
    return float(x) if x is not None else 0.0


def _kw(value):
    return f"{value:,.1f} kW" if value >= 1 else f"{value:.3f} kW"


class _Builder:
    def __init__(self):
        self.labels, self.colors = [], []
        self.sources, self.targets, self.values, self.link_colors = [], [], [], []

    def node(self, label, color):
        self.labels.append(label)
        self.colors.append(color)
        return len(self.labels) - 1

    def link(self, src, label, value, color):
        """Adds `label` as a new node fed from `src`. Zero or negative flows
        are left out (Sankey links must be positive)."""
        value = _f(value)
        if value <= 1e-6:
            return
        dst = self.node(f"{label}: {_kw(value)}", color)
        self.sources.append(src)
        self.targets.append(dst)
        self.values.append(value)
        self.link_colors.append(color)

    def feed(self, label, value, dst, color=INPUT):
        value = _f(value)
        if value <= 1e-6:
            return
        src = self.node(f"{label}: {_kw(value)}", color)
        self.sources.append(src)
        self.targets.append(dst)
        self.values.append(value)
        self.link_colors.append(color)

    def result(self):
        return dict(labels=self.labels, node_colors=self.colors, sources=self.sources,
                    targets=self.targets, values=self.values, link_colors=self.link_colors)


def _rankine(ex, cycle_name):
    """Steam, ORC and transcritical CO2: heater, turbine, condenser, pump.
    Same scheme as the overall diagram in steam.py."""
    b = _Builder()
    cyc = b.node(cycle_name, CYCLE)
    b.feed("Exergy from flue gas", ex["heater"]["hot_change"], cyc)
    b.link(cyc, "Net power output", _f(ex["turbine"]["work"]) - _f(ex["pump"]["work"]), USEFUL)
    b.link(cyc, "Destruction – heater", ex["heater"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – turbine", ex["turbine"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – pump", ex["pump"]["destroyed"], DESTROYED)
    _condenser(b, cyc, ex["condenser"], "condenser")
    return b.result()


def _condenser(b, cyc, hx, name):
    """Splits the exergy the working fluid gives up in a condenser/cooler
    (hot_change) into what the cooling water carries away and what is
    destroyed. When the cooling water enters below the 25 °C reference
    temperature its exergy change is negative, so all of it counts as
    destruction -- this keeps the diagram balanced and free of negative flows."""
    released = _f(hx["hot_change"])
    to_water = min(max(_f(hx["cold_change"]), 0.0), released)
    b.link(cyc, f"Destruction – {name}", released - to_water, DESTROYED)
    b.link(cyc, "Lost to cooling water", to_water, LOSS)


def _super(ex):
    """Recompression sCO2 cycle. Same scheme as exergy_flows2 in super.py."""
    b = _Builder()
    cyc = b.node("sCO₂ cycle", CYCLE)
    b.feed("Exergy added in flue gas heater", ex["heater"], cyc)
    net = (_f(ex["turbine"]["work"]) - _f(ex["main_compressor"]["work"])
           - _f(ex["bypass_compressor"]["work"]))
    b.link(cyc, "Net power output", net, USEFUL)
    b.link(cyc, "To bottoming cycle", ex["bt"]["cold_change"], LOSS)
    b.link(cyc, "Destruction – turbine", ex["turbine"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – HTR", ex["htr"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – LTR", ex["ltr"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – bottoming-cycle HX", ex["bt"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – main compressor", ex["main_compressor"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – bypass compressor", ex["bypass_compressor"]["destroyed"], DESTROYED)
    b.link(cyc, "Destruction – mixer", ex["mixer"]["destroyed"], DESTROYED)
    _condenser(b, cyc, ex["cooler"], "cooler")
    return b.result()


def _libr(ex):
    """LiBr absorption chiller. libr.py only evaluates component exergy for
    the pump and solution heat exchanger, so the desorber, absorber,
    condenser and evaporator are shown together as the balance."""
    b = _Builder()
    cyc = b.node("LiBr chiller", CYCLE)
    ex_in, pump_w = _f(ex["ex_in"]), _f(ex["pump"]["work"])
    b.feed("Exergy from flue gas", ex_in, cyc)
    b.feed("Pump work", pump_w, cyc)
    cooling = _f(ex["ex_out"])
    pump_d, shx_d = _f(ex["pump"]["destroyed"]), _f(ex["solution_hx"]["destroyed"])
    b.link(cyc, "Cooling exergy output", cooling, USEFUL)
    b.link(cyc, "Destruction – solution HX", shx_d, DESTROYED)
    b.link(cyc, "Destruction – pump", pump_d, DESTROYED)
    b.link(cyc, "Destruction & losses – desorber, absorber, condenser, evaporator",
           ex_in + pump_w - cooling - pump_d - shx_d, DESTROYED)
    return b.result()


def build_flows(cycle_key, exergy):
    if cycle_key == "super":
        return _super(exergy)
    if cycle_key == "libr":
        return _libr(exergy)
    names = {"steam": "Steam Rankine cycle", "orc": "Organic Rankine cycle", "trans": "Transcritical CO₂ cycle"}
    return _rankine(exergy, names[cycle_key])


def figure(flows, title):
    import plotly.graph_objects as go
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        valueformat=",.1f",
        valuesuffix=" kW",
        node=dict(pad=18, thickness=18, line=dict(color="rgba(0,0,0,0.3)", width=0.5),
                  label=flows["labels"], color=flows["node_colors"]),
        link=dict(source=flows["sources"], target=flows["targets"], value=flows["values"],
                  color=[c + "55" for c in flows["link_colors"]]),
    ))
    fig.update_layout(title_text=title, font_size=12, height=520, margin=dict(l=10, r=10, t=50, b=10))
    return fig
