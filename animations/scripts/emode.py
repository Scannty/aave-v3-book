from manim import *

class EModeComparison(Scene):
    """Side-by-side comparison of normal mode vs E-Mode capital efficiency."""

    def construct(self):
        title = Text("E-Mode: Capital Efficiency", font_size=36, color=WHITE).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=1)
        self.wait(0.5)

        # Two scenarios: Normal vs E-Mode
        # Stablecoins: Supply 10,000 USDC, borrow DAI

        normal_title = Text("Normal Mode", font_size=26, color=RED_B, weight=BOLD)
        emode_title = Text("E-Mode (Stablecoins)", font_size=26, color=GREEN, weight=BOLD)

        # Normal mode params
        normal_ltv = 0.77
        normal_liq = 0.80
        # E-Mode params
        emode_ltv = 0.93
        emode_liq = 0.95

        collateral = 10000  # 10,000 USDC

        normal_borrow = collateral * normal_ltv  # 7,700
        emode_borrow = collateral * emode_ltv    # 9,300

        # Build normal mode column
        normal_box = VGroup(
            normal_title,
            Text(f"Collateral: $10,000 USDC", font_size=20, color=GREY_B),
            Text(f"LTV: {normal_ltv*100:.0f}%", font_size=20, color=GREY_B),
            Text(f"Liq. Threshold: {normal_liq*100:.0f}%", font_size=20, color=GREY_B),
            Text("───────────────", font_size=16, color=GREY),
            Text(f"Max Borrow: ${normal_borrow:,.0f} DAI", font_size=22, color=RED_B, weight=BOLD),
        ).arrange(DOWN, buff=0.2)

        # Build e-mode column
        emode_box = VGroup(
            emode_title,
            Text(f"Collateral: $10,000 USDC", font_size=20, color=GREY_B),
            Text(f"LTV: {emode_ltv*100:.0f}%", font_size=20, color=GREY_B),
            Text(f"Liq. Threshold: {emode_liq*100:.0f}%", font_size=20, color=GREY_B),
            Text("───────────────", font_size=16, color=GREY),
            Text(f"Max Borrow: ${emode_borrow:,.0f} DAI", font_size=22, color=GREEN, weight=BOLD),
        ).arrange(DOWN, buff=0.2)

        boxes = VGroup(normal_box, emode_box).arrange(RIGHT, buff=2).shift(UP * 0.3)

        # Animate left column
        for mob in normal_box:
            self.play(Write(mob), run_time=0.5)

        self.wait(0.5)

        # Animate right column
        for mob in emode_box:
            self.play(Write(mob), run_time=0.5)

        # Show the difference
        diff = emode_borrow - normal_borrow
        pct_gain = (diff / normal_borrow) * 100

        diff_text = VGroup(
            Text(f"E-Mode gives ${diff:,.0f} more borrowing power", font_size=24, color=YELLOW),
            Text(f"That's {pct_gain:.0f}% more capital efficient!", font_size=22, color=YELLOW),
        ).arrange(DOWN, buff=0.15).to_edge(DOWN, buff=0.8)

        arrow = Arrow(
            normal_box[-1].get_right(),
            emode_box[-1].get_left(),
            color=YELLOW, buff=0.3
        )
        gain_label = Text(f"+${diff:,.0f}", font_size=24, color=YELLOW).next_to(arrow, UP, buff=0.1)

        self.play(GrowArrow(arrow), Write(gain_label), run_time=1)
        self.play(Write(diff_text), run_time=1)
        self.wait(2)


class EModeBarChart(Scene):
    """Bar chart comparing LTV across different E-Mode categories."""

    def construct(self):
        title = Text("LTV Comparison: Normal vs E-Mode", font_size=34, color=WHITE).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=1)

        # Categories and their LTVs
        categories = [
            ("ETH\n(Normal)", 0.80, RED_B),
            ("ETH\n(E-Mode)", 0.93, GREEN),
            ("USDC\n(Normal)", 0.77, RED_B),
            ("USDC\n(E-Mode)", 0.93, GREEN),
            ("BTC\n(Normal)", 0.73, RED_B),
            ("BTC\n(E-Mode)", 0.93, GREEN),
        ]

        bars = VGroup()
        labels = VGroup()
        pct_labels = VGroup()

        bar_width = 0.8
        max_height = 4.5
        spacing = 1.3

        start_x = -3.5

        for i, (name, ltv, color) in enumerate(categories):
            x = start_x + i * spacing
            height = ltv * max_height

            bar = Rectangle(
                width=bar_width,
                height=height,
                fill_color=color,
                fill_opacity=0.7,
                stroke_color=color,
            )
            bar.move_to(np.array([x, -2.5 + height / 2, 0]))

            label = Text(name, font_size=16, color=GREY_B).next_to(bar, DOWN, buff=0.15)
            pct = Text(f"{ltv*100:.0f}%", font_size=20, color=WHITE, weight=BOLD).next_to(bar, UP, buff=0.1)

            bars.add(bar)
            labels.add(label)
            pct_labels.add(pct)

        # Animate bars growing
        for bar, label, pct in zip(bars, labels, pct_labels):
            bar_copy = bar.copy()
            bar_copy.stretch(0.01, 1, about_edge=DOWN)
            self.add(bar_copy)
            self.play(
                Transform(bar_copy, bar),
                FadeIn(label),
                run_time=0.8
            )
            self.play(Write(pct), run_time=0.5)

        # Annotation
        note = Text(
            "E-Mode allows ~93% LTV for correlated assets\nvs 73-80% in normal mode",
            font_size=22, color=YELLOW
        ).to_edge(DOWN, buff=0.5)
        self.play(Write(note), run_time=1)
        self.wait(2)
