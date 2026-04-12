from manim import *
import numpy as np

class HealthFactorVisualization(Scene):
    """Animates health factor declining as collateral price drops,
    showing when liquidation triggers."""

    def construct(self):
        title = Text("Health Factor & Liquidation", font_size=36, color=WHITE).to_edge(UP, buff=0.4)

        # Scenario: User supplies 10 ETH, borrows 15,000 USDC
        # ETH liquidation threshold = 82.5%
        # Starting ETH price = $2,000

        axes = Axes(
            x_range=[1000, 2100, 100],
            y_range=[0, 2.5, 0.5],
            x_length=10,
            y_length=5.5,
            axis_config={"color": WHITE, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.3)

        x_label = Text("ETH Price ($)", font_size=22, color=GREY_B).next_to(axes.c2p(2100, 0), DOWN + RIGHT, buff=0.2)
        y_label = Text("Health Factor", font_size=22, color=GREY_B).next_to(axes.c2p(1000, 2.5), UP + LEFT, buff=0.2)

        # Price labels
        price_labels = VGroup()
        for p in [1000, 1200, 1400, 1600, 1800, 2000]:
            l = Text(f"${p}", font_size=16, color=GREY_B)
            l.next_to(axes.c2p(p, 0), DOWN, buff=0.15)
            price_labels.add(l)

        # HF labels
        hf_labels = VGroup()
        for v in [0.5, 1.0, 1.5, 2.0]:
            l = Text(f"{v:.1f}", font_size=18, color=GREY_B)
            l.next_to(axes.c2p(1000, v), LEFT, buff=0.15)
            hf_labels.add(l)

        # Health factor formula:
        # HF = (collateral_value * liquidation_threshold) / debt
        # HF = (10 * ETH_price * 0.825) / 15000
        eth_amount = 10
        liq_threshold = 0.825
        debt = 15000

        def health_factor(price):
            return (eth_amount * price * liq_threshold) / debt

        # The curve
        hf_curve = axes.plot(health_factor, x_range=[1000, 2100, 5], color=BLUE)

        # Liquidation line at HF = 1
        liq_line = DashedLine(
            axes.c2p(1000, 1), axes.c2p(2100, 1),
            color=RED, dash_length=0.15
        )
        liq_text = Text("HF = 1 (Liquidation)", font_size=20, color=RED).next_to(
            axes.c2p(1500, 1), UP, buff=0.15
        )

        # Find the price where HF = 1
        # 1 = (10 * P * 0.825) / 15000 → P = 15000 / (10 * 0.825) = 1818.18
        liq_price = debt / (eth_amount * liq_threshold)
        liq_price_line = DashedLine(
            axes.c2p(liq_price, 0), axes.c2p(liq_price, 1),
            color=YELLOW, dash_length=0.1
        )
        liq_price_label = Text(f"${liq_price:.0f}", font_size=20, color=YELLOW).next_to(
            axes.c2p(liq_price, 0), DOWN, buff=0.3
        )

        # Position info box
        info = VGroup(
            Text("Position:", font_size=22, color=WHITE, weight=BOLD),
            Text("Collateral: 10 ETH", font_size=20, color=GREY_B),
            Text("Debt: 15,000 USDC", font_size=20, color=GREY_B),
            Text("Liq. Threshold: 82.5%", font_size=20, color=GREY_B),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).to_corner(UL, buff=0.8).shift(DOWN * 0.5)

        # Danger zone shading
        danger_zone = Polygon(
            axes.c2p(1000, 0),
            axes.c2p(liq_price, 0),
            axes.c2p(liq_price, 1),
            axes.c2p(1000, health_factor(1000)),
            fill_color=RED,
            fill_opacity=0.12,
            stroke_width=0,
        )

        safe_zone_label = Text("SAFE", font_size=28, color=GREEN, weight=BOLD).move_to(axes.c2p(1950, 1.8))
        danger_zone_label = Text("LIQUIDATABLE", font_size=22, color=RED, weight=BOLD).move_to(axes.c2p(1200, 0.5))

        # Animation
        self.play(Write(title), run_time=1)
        self.play(Create(axes), Write(x_label), Write(y_label), run_time=1.5)
        self.play(FadeIn(price_labels), FadeIn(hf_labels), run_time=0.8)
        self.play(FadeIn(info), run_time=0.8)

        # Draw liquidation line first
        self.play(Create(liq_line), Write(liq_text), run_time=1)

        # Draw the HF curve
        self.play(Create(hf_curve), run_time=2)

        # Show danger zone
        self.play(FadeIn(danger_zone), run_time=0.8)
        self.play(Create(liq_price_line), Write(liq_price_label), run_time=1)
        self.play(Write(safe_zone_label), Write(danger_zone_label), run_time=0.8)

        # Animate price dropping
        dot = Dot(axes.c2p(2000, health_factor(2000)), color=YELLOW, radius=0.1)
        hf_value = Text(f"HF = {health_factor(2000):.2f}", font_size=24, color=GREEN).next_to(dot, UR, buff=0.15)

        self.play(FadeIn(dot), Write(hf_value), run_time=0.5)
        self.wait(1)

        # Drop through price levels
        for target_price, col in [(1900, GREEN), (1700, YELLOW), (1500, ORANGE), (1300, RED)]:
            new_hf = health_factor(target_price)
            new_pos = axes.c2p(target_price, new_hf)
            color = GREEN if new_hf > 1.5 else (YELLOW if new_hf > 1.2 else (ORANGE if new_hf > 1 else RED))
            new_label = Text(f"HF = {new_hf:.2f}", font_size=24, color=color).next_to(new_pos, UR, buff=0.15)

            self.play(
                dot.animate.move_to(new_pos),
                FadeOut(hf_value),
                run_time=1.5
            )
            hf_value = new_label
            self.play(Write(hf_value), run_time=0.5)
            self.wait(0.5)

        # Flash "LIQUIDATED" at the end
        liquidated = Text("LIQUIDATED!", font_size=48, color=RED, weight=BOLD).move_to(ORIGIN)
        flash_rect = SurroundingRectangle(liquidated, color=RED, buff=0.3, corner_radius=0.1)
        self.play(FadeIn(liquidated), Create(flash_rect), run_time=0.8)
        self.play(
            liquidated.animate.scale(1.1),
            rate_func=there_and_back,
            run_time=0.8
        )
        self.wait(2)


class HealthFactorFormula(Scene):
    """Explains the health factor formula step by step."""

    def construct(self):
        title = Text("Health Factor Formula", font_size=36, color=WHITE).to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1)

        # Main formula
        formula = Text(
            "HF = Sum(Collateral x Price x LiqThreshold) / TotalDebt",
            font_size=28, color=WHITE
        )
        self.play(Write(formula), run_time=1.5)
        self.wait(1)

        # Move formula up
        self.play(formula.animate.shift(UP * 1.5), run_time=0.8)

        # Example
        example_title = Text("Example:", font_size=26, color=YELLOW).shift(UP * 0.2 + LEFT * 3)

        lines = VGroup(
            Text("10 ETH x $2,000 x 0.825 = $16,500", font_size=24, color=GREY_B),
            Text("Total Debt = $15,000 (USDC)", font_size=24, color=GREY_B),
            Text("HF = $16,500 / $15,000 = 1.10", font_size=28, color=GREEN),
        ).arrange(DOWN, buff=0.4).shift(DOWN * 1.2)

        self.play(Write(example_title), run_time=0.8)
        for line in lines:
            self.play(Write(line), run_time=1)
            self.wait(0.5)

        # HF interpretation
        interp = VGroup(
            Text("HF > 1  →  Position is safe", font_size=24, color=GREEN),
            Text("HF = 1  →  Liquidation threshold", font_size=24, color=YELLOW),
            Text("HF < 1  →  Can be liquidated", font_size=24, color=RED),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).to_edge(DOWN, buff=0.6)

        self.play(Write(interp), run_time=1)
        self.wait(2)
