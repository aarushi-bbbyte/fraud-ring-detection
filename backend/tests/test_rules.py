"""Detection rules on small hand-built graphs: each rule should flag exactly what it should."""

from __future__ import annotations

from dataclasses import replace

from fraudring.detection.config import RuleConfig
from fraudring.detection.cycles import find_cycles
from fraudring.detection.fans import find_fans
from fraudring.detection.run import run_detection

CFG = RuleConfig(
    cycle_max_hops=6,
    cycle_window_hours=24.0,
    cycle_amount_tolerance=0.2,
    fan_window_hours=24.0,
    fan_in_min_senders=5,
    fan_out_min_receivers=5,
    hub_degree_cap=50,
)


def all_hits(driver, cfg=CFG):
    return find_cycles(driver, cfg), find_fans(driver, cfg, "in"), find_fans(driver, cfg, "out")


def add_noise(g):
    """Ordinary traffic around the pattern: a chain and a small tree, no cycles, low fan."""
    g.send("N:1", "N:2", 1, 50)
    g.send("N:2", "N:3", 2, 70)
    g.send("N:3", "N:4", 3, 20)
    for leaf in ("N:5", "N:6", "N:7"):
        g.send("N:1", leaf, 5, 300)


def five_cycle(g, hours=(0, 1, 2, 3, 4), amounts=(1000, 990, 980, 975, 960)):
    nodes = ["C:A", "C:B", "C:C", "C:D", "C:E"]
    return [
        g.send(nodes[i], nodes[(i + 1) % 5], h, usd)
        for i, (h, usd) in enumerate(zip(hours, amounts))
    ]


# --- cycles -------------------------------------------------------------------

def test_five_node_cycle_is_caught_and_nothing_else(graph):
    txs = five_cycle(graph)
    add_noise(graph)
    graph.commit()

    cycles, fan_in, fan_out = all_hits(graph.driver)
    assert len(cycles) == 1
    assert set(cycles[0].tx_ids) == set(txs)
    assert cycles[0].accounts == ("C:A", "C:B", "C:C", "C:D", "C:E")
    assert fan_in == [] and fan_out == []


def test_cycle_hops_must_be_time_ordered(graph):
    five_cycle(graph, hours=(0, 2, 1, 3, 4))  # third hop happens before the second
    graph.commit()
    assert find_cycles(graph.driver, CFG) == []


def test_cycle_must_close_within_window(graph):
    five_cycle(graph, hours=(0, 1, 2, 3, 30))
    graph.commit()
    assert find_cycles(graph.driver, CFG) == []
    assert len(find_cycles(graph.driver, replace(CFG, cycle_window_hours=36.0))) == 1


def test_cycle_longer_than_max_hops_is_ignored(graph):
    nodes = [f"L:{i}" for i in range(7)]
    for i in range(7):
        graph.send(nodes[i], nodes[(i + 1) % 7], i, 1000)
    graph.commit()
    assert find_cycles(graph.driver, CFG) == []
    assert len(find_cycles(graph.driver, replace(CFG, cycle_max_hops=7))) == 1


def test_cycle_hop_amount_must_be_similar(graph):
    five_cycle(graph, amounts=(1000, 990, 2500, 2480, 2470))  # +150% on one hop
    graph.commit()
    assert find_cycles(graph.driver, CFG) == []


def test_self_loops_are_not_cycles(graph):
    graph.send("S:1", "S:1", 0)
    graph.send("S:1", "S:1", 1)
    graph.commit()
    assert find_cycles(graph.driver, CFG) == []


# --- fan-in / fan-out -----------------------------------------------------------

def test_fan_in_counts_distinct_senders_in_window(graph):
    txs = [graph.send(f"F:s{i}", "F:hub", i, 500) for i in range(6)]
    txs.append(graph.send("F:s0", "F:hub", 7, 500))  # repeat sender: counted once
    add_noise(graph)
    graph.commit()

    cycles, fan_in, fan_out = all_hits(graph.driver)
    assert cycles == [] and fan_out == []
    assert len(fan_in) == 1
    hit = fan_in[0]
    assert hit.hub == "F:hub"
    assert hit.counterparties == 6
    assert set(hit.tx_ids) == set(txs)


def test_fan_in_spread_beyond_window_is_ignored(graph):
    for i in range(6):
        graph.send(f"F:s{i}", "F:hub", i * 20, 500)  # 6 senders over 100 hours
    graph.commit()
    assert find_fans(graph.driver, CFG, "in") == []


def test_fan_out_counts_distinct_receivers_in_window(graph):
    txs = [graph.send("O:hub", f"O:r{i}", i, 500) for i in range(5)]
    add_noise(graph)
    graph.commit()

    cycles, fan_in, fan_out = all_hits(graph.driver)
    assert cycles == [] and fan_in == []
    assert [(f.hub, f.counterparties) for f in fan_out] == [("O:hub", 5)]
    assert set(fan_out[0].tx_ids) == set(txs)


def test_fan_below_threshold_is_ignored(graph):
    for i in range(4):  # one short of the threshold
        graph.send("O:hub", f"O:r{i}", i, 500)
    graph.commit()
    assert find_fans(graph.driver, CFG, "out") == []


def test_hubs_above_degree_cap_are_skipped(graph):
    for i in range(CFG.hub_degree_cap + 10):
        graph.send("H:bank", f"H:r{i}", i * 0.1, 100)
    graph.commit()
    assert find_fans(graph.driver, CFG, "out") == []


# --- clean graph ----------------------------------------------------------------

def test_clean_graph_raises_nothing(graph):
    add_noise(graph)
    for i in range(4):
        graph.send(f"Q:{i}", f"Q:{i + 1}", i, 100)  # a 5-account chain
    graph.commit()
    assert all_hits(graph.driver) == ([], [], [])


# --- alerts and rings -----------------------------------------------------------

def test_alerts_are_stored_with_reasons_and_grouped_into_rings(graph):
    five_cycle(graph)
    for i in range(5):  # separate fan-in ring
        graph.send(f"F:s{i}", "F:hub", i, 500)
    add_noise(graph)
    graph.commit()

    summary = run_detection(graph.driver, CFG)
    assert (summary.cycles, summary.fan_in, summary.fan_out) == (1, 1, 0)
    assert sorted(len(r) for r in summary.rings) == [5, 6]

    rows = graph.driver.execute_query(
        """
        MATCH (al:Alert)-[:PART_OF]->(r:Ring)
        RETURN al.rule AS rule, al.reason AS reason, r.size AS ring_size
        ORDER BY rule
        """
    ).records
    assert [(r["rule"], r["ring_size"]) for r in rows] == [("cycle", 5), ("fan_in", 6)]
    assert rows[0]["reason"].startswith("Part of a 5-hop cycle: $1,000 left C:A")
    assert rows[1]["reason"].startswith("Fan-in: received from 5 distinct accounts")


def test_alerts_sharing_an_account_form_one_ring(graph):
    five_cycle(graph)
    for i in range(5):  # the cycle origin is also a fan-in hub
        graph.send(f"F:s{i}", "C:A", 10 + i, 500)
    graph.commit()

    summary = run_detection(graph.driver, CFG)
    assert [len(r) for r in summary.rings] == [10]


def test_shared_counterparty_does_not_merge_rings(graph):
    # An ordinary account that pays two unrelated fan-in hubs.
    for hub in ("F:hub1", "F:hub2"):
        graph.send("F:customer", hub, 0, 500)
        for i in range(4):
            graph.send(f"{hub}:s{i}", hub, 1 + i, 500)
    graph.commit()

    summary = run_detection(graph.driver, CFG)
    assert summary.fan_in == 2
    assert sorted(len(r) for r in summary.rings) == [6, 6]
    assert sum("F:customer" in r for r in summary.rings) == 2


def test_fan_out_hub_paying_fan_in_hub_is_one_ring(graph):
    # Scatter-gather: the scattering hub pays the gathering hub directly.
    for i in range(4):
        graph.send("G:scatter", f"G:m{i}", i, 500)
        graph.send(f"G:x{i}", "G:gather", 10 + i, 500)
    graph.send("G:scatter", "G:gather", 5, 500)
    graph.commit()

    summary = run_detection(graph.driver, CFG)
    assert (summary.fan_in, summary.fan_out) == (1, 1)
    assert [len(r) for r in summary.rings] == [10]


def test_payment_outside_the_other_hubs_window_does_not_merge_rings(graph):
    # The scatter hub pays the gather hub, but days before the gather hub's burst.
    for i in range(4):
        graph.send("G:scatter", f"G:m{i}", i, 500)
        graph.send(f"G:x{i}", "G:gather", 100 + i, 500)
    graph.send("G:scatter", "G:gather", 5, 500)
    graph.send("G:y", "G:gather", 104, 500)  # 5th distinct sender inside the burst
    graph.commit()

    summary = run_detection(graph.driver, CFG)
    assert (summary.fan_in, summary.fan_out) == (1, 1)
    assert sorted(len(r) for r in summary.rings) == [6, 6]
