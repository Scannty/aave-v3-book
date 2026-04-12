from manim import *

class InterestRateCurve(Scene):
    """Animated interest rate curve showing the kink model.
    Draws borrow rate and supply rate vs utilization, highlighting the kink point.
    """

    def construct(self):
        # Parameters (USDC-like)
        optimal_u = 0.9
        base_rate = 0.0
        slope1 = 0.04  # 4%
        slope2 = 0.60  # 60%
        reserve_factor = 0.10

        def borrow_rate(u):
            if u <= optimal_u:
                return base_rate + (u / optimal_u) * slope1
            else:
                return base_rate + slope1 + ((u - optimal_u) / (1 - optimal_u)) * slope2

        def supply_rate(u):
            return borrow_rate(u) * u * (1 - reserve_factor)

        # Axes
        axes = Axes(
            x_range=[0, 1, 0.1],
            y_range=[0, 0.7, 0.1],
            x_length=10,
            y_length=6,
            axis_config={"color": WHITE, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.3)

        x_label = Text("Utilization", font_size=22, color=GREY_B).next_to(axes.c2p(1, 0), DOWN, buff=0.4)
        y_label = Text("Interest Rate", font_size=22, color=GREY_B).next_to(axes.c2p(0, 0.7), LEFT, buff=0.3)

        # Percentage labels on axes
        x_pct_labels = VGroup()
        for val in [0.2, 0.4, 0.6, 0.8, 1.0]:
            label = Text(f"{int(val*100)}%", font_size=20, color=GREY_B)
            label.next_to(axes.c2p(val, 0), DOWN, buff=0.2)
            x_pct_labels.add(label)

        y_pct_labels = VGroup()
        for val in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
            label = Text(f"{int(val*100)}%", font_size=20, color=GREY_B)
            label.next_to(axes.c2p(0, val), LEFT, buff=0.2)
            y_pct_labels.add(label)

        # Title
        title = Text("Aave V3 Interest Rate Model", font_size=36, color=WHITE).to_edge(UP, buff=0.4)

        # Kink line
        kink_line = DashedLine(
            axes.c2p(optimal_u, 0),
            axes.c2p(optimal_u, 0.65),
            color=YELLOW,
            dash_length=0.1,
        )
        kink_label = Text("Optimal\nUtilization", font_size=18, color=YELLOW).next_to(
            axes.c2p(optimal_u, 0.65), UP, buff=0.15
        )

        # Borrow rate curve
        borrow_curve_left = axes.plot(
            borrow_rate, x_range=[0, optimal_u, 0.005], color=RED
        )
        borrow_curve_right = axes.plot(
            borrow_rate, x_range=[optimal_u, 1, 0.005], color=RED
        )

        # Supply rate curve
        supply_curve = axes.plot(
            supply_rate, x_range=[0, 1, 0.005], color=GREEN
        )

        # Legend
        borrow_legend = VGroup(
            Line(ORIGIN, RIGHT * 0.5, color=RED),
            Text("Borrow Rate", font_size=22, color=RED),
        ).arrange(RIGHT, buff=0.2)
        supply_legend = VGroup(
            Line(ORIGIN, RIGHT * 0.5, color=GREEN),
            Text("Supply Rate", font_size=22, color=GREEN),
        ).arrange(RIGHT, buff=0.2)
        legend = VGroup(borrow_legend, supply_legend).arrange(DOWN, aligned_edge=LEFT, buff=0.15)
        legend.to_corner(DR, buff=0.8).shift(UP * 1.5)

        # Slope labels
        slope1_label = Text("Slope 1 (gentle)", font_size=18, color=RED_B).move_to(
            axes.c2p(0.45, 0.06)
        )
        slope2_label = Text("Slope 2 (steep)", font_size=18, color=RED_B).move_to(
            axes.c2p(0.95, 0.35)
        ).rotate(55 * DEGREES)

        # Animation sequence
        self.play(Write(title), run_time=1)
        self.play(Create(axes), Write(x_label), Write(y_label), run_time=1.5)
        self.play(FadeIn(x_pct_labels), FadeIn(y_pct_labels), run_time=0.8)

        # Draw gentle slope
        self.play(Create(borrow_curve_left), run_time=2)
        self.play(FadeIn(slope1_label), run_time=0.5)

        # Show kink point
        self.play(Create(kink_line), Write(kink_label), run_time=1)

        # Draw steep slope
        self.play(Create(borrow_curve_right), run_time=1.5)
        self.play(FadeIn(slope2_label), run_time=0.5)

        # Draw supply rate
        self.play(Create(supply_curve), run_time=2)
        self.play(FadeIn(legend), run_time=0.8)

        # Animate a dot moving along the curve
        dot = Dot(color=YELLOW, radius=0.08)
        rate_label = Text("0.0%", font_size=24, color=YELLOW)

        def update_dot(mob, alpha):
            u = max(alpha, 0.001)
            r = borrow_rate(u)
            mob.move_to(axes.c2p(u, r))

        def update_label(mob, alpha):
            u = max(alpha, 0.001)
            r = borrow_rate(u) * 100
            new_label = Text(f"{r:.1f}%", font_size=24, color=YELLOW)
            new_label.next_to(axes.c2p(u, borrow_rate(u)), UP, buff=0.2)
            mob.become(new_label)

        dot.move_to(axes.c2p(0, 0))
        rate_label.next_to(dot, UP, buff=0.2)

        self.play(FadeIn(dot), FadeIn(rate_label), run_time=0.5)

        # Sweep from 0 to 100% utilization
        self.play(
            UpdateFromAlphaFunc(dot, update_dot),
            UpdateFromAlphaFunc(rate_label, update_label),
            run_time=5,
            rate_func=linear,
        )
        self.wait(2)


class UtilizationShift(Scene):
    """Shows how rates change as utilization moves — a user borrows and utilization increases."""

    def construct(self):
        optimal_u = 0.9
        base_rate = 0.0
        slope1 = 0.04
        slope2 = 0.60

        def borrow_rate(u):
            if u <= optimal_u:
                return base_rate + (u / optimal_u) * slope1
            else:
                return base_rate + slope1 + ((u - optimal_u) / (1 - optimal_u)) * slope2

        axes = Axes(
            x_range=[0, 1, 0.1],
            y_range=[0, 0.7, 0.1],
            x_length=10,
            y_length=6,
            axis_config={"color": WHITE, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.3)

        title = Text("What Happens When Utilization Increases", font_size=32, color=WHITE).to_edge(UP, buff=0.4)

        borrow_curve = axes.plot(borrow_rate, x_range=[0, 1, 0.005], color=RED)

        kink_line = DashedLine(
            axes.c2p(optimal_u, 0), axes.c2p(optimal_u, 0.65),
            color=YELLOW, dash_length=0.1
        )

        # Starting state: 70% utilization
        start_u = 0.70
        end_u = 0.95

        start_dot = Dot(axes.c2p(start_u, borrow_rate(start_u)), color=BLUE, radius=0.1)
        end_dot = Dot(axes.c2p(end_u, borrow_rate(end_u)), color=RED_A, radius=0.1)

        start_label = Text(f"Before: {borrow_rate(start_u)*100:.1f}% APR", font_size=22, color=BLUE).next_to(start_dot, UP + LEFT, buff=0.2)
        end_label = Text(f"After: {borrow_rate(end_u)*100:.1f}% APR", font_size=22, color=RED_A).next_to(end_dot, UP + RIGHT, buff=0.2)

        event_text = Text("Large borrow pushes utilization\npast optimal point", font_size=24, color=YELLOW).to_edge(DOWN, buff=0.5)

        # Build scene
        self.play(Write(title), run_time=1)
        self.play(Create(axes), Create(borrow_curve), Create(kink_line), run_time=1.5)

        self.play(FadeIn(start_dot), Write(start_label), run_time=0.8)
        self.wait(1)

        self.play(Write(event_text), run_time=1)

        # Animate the shift
        arrow = Arrow(
            axes.c2p(start_u, borrow_rate(start_u)),
            axes.c2p(end_u, borrow_rate(end_u)),
            color=YELLOW, buff=0.15
        )
        self.play(GrowArrow(arrow), run_time=1.5)
        self.play(FadeIn(end_dot), Write(end_label), run_time=0.8)
        self.wait(2)
