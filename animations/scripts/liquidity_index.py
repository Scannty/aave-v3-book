from manim import *
import numpy as np

class LiquidityIndexGrowth(Scene):
    """Animates the liquidity index growing over time, showing how scaled balances
    translate to actual balances."""

    def construct(self):
        title = Text("Liquidity Index Over Time", font_size=36, color=WHITE).to_edge(UP, buff=0.4)

        # Axes - leave more room at bottom and left
        axes = Axes(
            x_range=[0, 365, 60],
            y_range=[1.0, 1.08, 0.02],
            x_length=9,
            y_length=5,
            axis_config={"color": WHITE, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.3 + RIGHT * 0.3)

        x_label = Text("Days", font_size=20, color=GREY_B).next_to(axes.c2p(365, 1.0), RIGHT, buff=0.2)

        # Day labels - fewer to avoid crowding
        day_labels = VGroup()
        for d in [0, 60, 120, 180, 240, 300, 365]:
            l = Text(str(d), font_size=16, color=GREY_B)
            l.next_to(axes.c2p(d, 1.0), DOWN, buff=0.15)
            day_labels.add(l)

        # Index labels - shifted left to not overlap axis
        idx_labels = VGroup()
        for v in [1.00, 1.02, 1.04, 1.06, 1.08]:
            l = Text(f"{v:.2f}", font_size=16, color=GREY_B)
            l.next_to(axes.c2p(0, v), LEFT, buff=0.2)
            idx_labels.add(l)

        # Simulate index growth with variable utilization
        def index_value(day):
            result = 1.0
            for d in range(int(day)):
                if d < 120:
                    r = 0.05 / 365
                elif d < 240:
                    r = 0.08 / 365
                else:
                    r = 0.03 / 365
                result *= (1 + r)
            return result

        # Pre-compute
        days = np.arange(0, 366)
        values = [index_value(d) for d in days]

        index_curve = axes.plot_line_graph(
            x_values=days,
            y_values=values,
            line_color=BLUE,
            add_vertex_dots=False,
        )

        # Period annotations - single line, positioned clearly above curve
        low_period = Text("Normal util.", font_size=16, color=GREEN).move_to(axes.c2p(60, 1.065))
        high_period = Text("High util.", font_size=16, color=RED).move_to(axes.c2p(180, 1.065))
        cool_period = Text("Low util.", font_size=16, color=GREEN).move_to(axes.c2p(300, 1.065))

        # Background shading for high utilization period
        high_rect = Rectangle(
            width=axes.c2p(240, 0)[0] - axes.c2p(120, 0)[0],
            height=axes.c2p(0, 1.08)[1] - axes.c2p(0, 1.0)[1],
            fill_color=RED,
            fill_opacity=0.08,
            stroke_width=0,
        ).move_to(axes.c2p(180, 1.04))

        self.play(FadeIn(title), run_time=1)
        self.play(Create(axes), FadeIn(x_label), run_time=1.5)
        self.play(FadeIn(day_labels), FadeIn(idx_labels), run_time=0.8)

        # Draw the curve progressively
        self.play(Create(index_curve), run_time=5, rate_func=linear)

        self.play(FadeIn(high_rect), run_time=0.5)
        self.play(FadeIn(low_period), FadeIn(high_period), FadeIn(cool_period), run_time=1)

        self.wait(2)


class ScaledBalanceExplained(Scene):
    """Visual explanation of how scaled balances work with the liquidity index."""

    def construct(self):
        title = Text("Scaled Balance vs Actual Balance", font_size=36, color=WHITE).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=1)

        # Create two bar charts side by side
        # Left: Scaled balances (constant)
        # Right: Actual balances (growing)

        left_title = Text("Stored (Scaled)", font_size=24, color=GREY_B)
        right_title = Text("Actual Balance", font_size=24, color=GREY_B)

        # Index progression
        indices = [1.00, 1.02, 1.05, 1.08]
        time_labels = ["T=0", "T=1", "T=2", "T=3"]

        alice_scaled = 1000  # constant
        bob_scaled = 952.38  # deposited when index=1.05

        frames = []
        for i, (idx, t) in enumerate(zip(indices, time_labels)):
            alice_actual = alice_scaled * idx

            frame = VGroup()

            # Time label
            t_label = Text(f"{t}  (index = {idx:.2f})", font_size=24, color=YELLOW)

            # Alice bar
            alice_bar_width = 3.5
            alice_scaled_bar = Rectangle(
                width=alice_bar_width * (alice_scaled / 1200),
                height=0.5,
                fill_color=BLUE,
                fill_opacity=0.7,
                stroke_color=BLUE,
            )
            alice_actual_bar = Rectangle(
                width=alice_bar_width * (alice_actual / 1200),
                height=0.5,
                fill_color=GREEN,
                fill_opacity=0.7,
                stroke_color=GREEN,
            )

            alice_s_label = Text(f"Alice: {alice_scaled:.0f}", font_size=20, color=WHITE)
            alice_a_label = Text(f"Alice: {alice_actual:.0f}", font_size=20, color=WHITE)

            # Arrange
            scaled_group = VGroup(alice_scaled_bar, alice_s_label).arrange(RIGHT, buff=0.2)
            actual_group = VGroup(alice_actual_bar, alice_a_label).arrange(RIGHT, buff=0.2)

            left_col = VGroup(Text("Scaled", font_size=20, color=GREY_B), scaled_group).arrange(DOWN, buff=0.2)
            right_col = VGroup(Text("Actual", font_size=20, color=GREY_B), actual_group).arrange(DOWN, buff=0.2)

            cols = VGroup(left_col, right_col).arrange(RIGHT, buff=1.5)

            frame = VGroup(t_label, cols).arrange(DOWN, buff=0.5).move_to(ORIGIN)
            frames.append(frame)

        # Formula
        formula = Text(
            "Actual Balance = Scaled Balance x Liquidity Index",
            font_size=28, color=WHITE
        ).to_edge(DOWN, buff=0.8)

        self.play(Write(formula), run_time=1)

        # Show each frame
        current = frames[0]
        self.play(FadeIn(current), run_time=0.8)
        self.wait(1)

        for next_frame in frames[1:]:
            self.play(FadeOut(current), run_time=0.5)
            self.play(FadeIn(next_frame), run_time=0.8)
            self.wait(1)
            current = next_frame

        self.wait(1.5)
