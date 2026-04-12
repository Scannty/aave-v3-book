from manim import *

class DelegateCallDiagram(Scene):
    """Animated diagram showing normal call vs delegatecall."""

    def construct(self):
        title = Text("Normal Call vs delegatecall", font_size=34, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        # ---- Normal Call (top) ----
        normal_label = Text("Normal call:", font_size=22, color=YELLOW, weight=BOLD).move_to(LEFT * 4.5 + UP * 1.5)

        user1 = VGroup(
            Rectangle(width=1.8, height=0.7, fill_color=BLUE, fill_opacity=0.2, stroke_color=BLUE),
            Text("User", font_size=16, color=BLUE),
        )
        user1[1].move_to(user1[0])
        user1.move_to(LEFT * 4 + UP * 0.5)

        proxy1 = VGroup(
            Rectangle(width=1.8, height=0.7, fill_color=GREEN, fill_opacity=0.2, stroke_color=GREEN),
            Text("Proxy", font_size=16, color=GREEN),
        )
        proxy1[1].move_to(proxy1[0])
        proxy1.move_to(LEFT * 1 + UP * 0.5)

        impl1 = VGroup(
            Rectangle(width=2.2, height=0.7, fill_color=RED_B, fill_opacity=0.2, stroke_color=RED_B),
            Text("Implementation", font_size=14, color=RED_B),
        )
        impl1[1].move_to(impl1[0])
        impl1.move_to(RIGHT * 2.5 + UP * 0.5)

        storage1 = Text("Uses Implementation's storage", font_size=14, color=RED_B).move_to(RIGHT * 2.5 + DOWN * 0.2)

        arr1a = Arrow(user1[0].get_right(), proxy1[0].get_left(), color=WHITE, buff=0.1, stroke_width=2)
        arr1b = Arrow(proxy1[0].get_right(), impl1[0].get_left(), color=WHITE, buff=0.1, stroke_width=2)

        # ---- delegatecall (bottom) ----
        deleg_label = Text("delegatecall:", font_size=22, color=YELLOW, weight=BOLD).move_to(LEFT * 4.5 + DOWN * 1.5)

        user2 = VGroup(
            Rectangle(width=1.8, height=0.7, fill_color=BLUE, fill_opacity=0.2, stroke_color=BLUE),
            Text("User", font_size=16, color=BLUE),
        )
        user2[1].move_to(user2[0])
        user2.move_to(LEFT * 4 + DOWN * 2.5)

        proxy2 = VGroup(
            Rectangle(width=1.8, height=0.7, fill_color=GREEN, fill_opacity=0.2, stroke_color=GREEN),
            Text("Proxy", font_size=16, color=GREEN),
        )
        proxy2[1].move_to(proxy2[0])
        proxy2.move_to(LEFT * 1 + DOWN * 2.5)

        impl2 = VGroup(
            Rectangle(width=2.2, height=0.7, fill_color=RED_B, fill_opacity=0.2, stroke_color=RED_B),
            Text("Implementation", font_size=14, color=RED_B),
        )
        impl2[1].move_to(impl2[0])
        impl2.move_to(RIGHT * 2.5 + DOWN * 2.5)

        storage2 = Text("Uses Proxy's storage!", font_size=14, color=GREEN, weight=BOLD).move_to(LEFT * 1 + DOWN * 3.3)

        arr2a = Arrow(user2[0].get_right(), proxy2[0].get_left(), color=WHITE, buff=0.1, stroke_width=2)
        arr2b = Arrow(proxy2[0].get_right(), impl2[0].get_left(), color=YELLOW, buff=0.1, stroke_width=2)

        # Animate normal call
        self.play(Write(normal_label), run_time=0.5)
        self.play(FadeIn(user1), run_time=0.5)
        self.play(GrowArrow(arr1a), FadeIn(proxy1), run_time=0.8)
        self.play(GrowArrow(arr1b), FadeIn(impl1), run_time=0.8)
        self.play(Write(storage1), run_time=0.5)
        self.wait(0.5)

        # Animate delegatecall
        self.play(Write(deleg_label), run_time=0.5)
        self.play(FadeIn(user2), run_time=0.5)
        self.play(GrowArrow(arr2a), FadeIn(proxy2), run_time=0.8)
        self.play(GrowArrow(arr2b), FadeIn(impl2), run_time=0.8)
        self.play(Write(storage2), run_time=0.5)

        # Highlight the key difference
        highlight = SurroundingRectangle(storage2, color=GREEN, buff=0.1)
        self.play(Create(highlight), run_time=0.5)
        self.wait(2)


class KinkModelChart(Scene):
    """Animated kink model for prerequisites chapter."""

    def construct(self):
        title = Text("The Kink Interest Rate Model", font_size=34, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        optimal_u = 0.8
        base_rate = 0.0
        slope1 = 0.05
        slope2 = 3.75  # steep: goes from 5% to 80% over 20% range

        def borrow_rate(u):
            if u <= optimal_u:
                return base_rate + (u / optimal_u) * slope1
            else:
                return base_rate + slope1 + ((u - optimal_u) / (1 - optimal_u)) * slope2

        axes = Axes(
            x_range=[0, 1, 0.1],
            y_range=[0, 0.85, 0.1],
            x_length=10,
            y_length=5.5,
            axis_config={"color": WHITE, "include_numbers": False},
            tips=False,
        ).shift(DOWN * 0.3)

        x_label = Text("Utilization", font_size=22, color=GREY_B).next_to(axes.c2p(1, 0), DOWN, buff=0.4)
        y_label = Text("Borrow Rate", font_size=22, color=GREY_B).next_to(axes.c2p(0, 0.85), LEFT, buff=0.3)

        # Axis labels
        x_pct = VGroup()
        for v in [0.2, 0.4, 0.6, 0.8, 1.0]:
            l = Text(f"{int(v*100)}%", font_size=18, color=GREY_B)
            l.next_to(axes.c2p(v, 0), DOWN, buff=0.15)
            x_pct.add(l)

        y_pct = VGroup()
        for v in [0.05, 0.20, 0.40, 0.60, 0.80]:
            l = Text(f"{int(v*100)}%", font_size=18, color=GREY_B)
            l.next_to(axes.c2p(0, v), LEFT, buff=0.15)
            y_pct.add(l)

        # Kink line
        kink_line = DashedLine(
            axes.c2p(optimal_u, 0), axes.c2p(optimal_u, 0.8),
            color=YELLOW, dash_length=0.1
        )
        kink_label = Text("U_optimal\n(the kink)", font_size=16, color=YELLOW).next_to(
            axes.c2p(optimal_u, 0), DOWN, buff=0.4
        )

        # Curves
        curve_left = axes.plot(borrow_rate, x_range=[0, optimal_u, 0.005], color=RED)
        curve_right = axes.plot(borrow_rate, x_range=[optimal_u, 1, 0.005], color=RED)

        # Slope annotations
        gentle = Text("Gentle slope", font_size=16, color=GREEN).move_to(axes.c2p(0.4, 0.08))
        steep = Text("Steep slope!", font_size=16, color=RED, weight=BOLD).move_to(axes.c2p(0.92, 0.45)).rotate(70 * DEGREES)

        self.play(Create(axes), Write(x_label), Write(y_label), run_time=1.5)
        self.play(FadeIn(x_pct), FadeIn(y_pct), run_time=0.8)

        self.play(Create(curve_left), run_time=2)
        self.play(Write(gentle), run_time=0.5)

        self.play(Create(kink_line), Write(kink_label), run_time=1)

        self.play(Create(curve_right), run_time=1.5)
        self.play(Write(steep), run_time=0.5)
        self.wait(0.5)

        # Explanation
        note = Text(
            "Below the kink: low rates encourage borrowing\nAbove the kink: high rates encourage repayment",
            font_size=18, color=GREY_B
        ).to_edge(DOWN, buff=0.3)
        self.play(Write(note), run_time=1)
        self.wait(2)


class LTVBufferZone(Scene):
    """Animated LTV vs Liquidation Threshold buffer zone."""

    def construct(self):
        title = Text("LTV vs Liquidation Threshold", font_size=34, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        # Number line from 0% to 100%
        line = NumberLine(
            x_range=[0, 100, 10],
            length=10,
            color=WHITE,
            include_numbers=False,
        ).shift(DOWN * 0.5)

        # Percentage labels
        pct_labels = VGroup()
        for v in [0, 20, 40, 60, 80, 82.5, 100]:
            l = Text(f"{v}%", font_size=16, color=GREY_B)
            l.next_to(line.n2p(v), DOWN, buff=0.2)
            pct_labels.add(l)

        # Zones
        safe_zone = Rectangle(
            width=line.n2p(80)[0] - line.n2p(0)[0],
            height=0.8,
            fill_color=GREEN, fill_opacity=0.2, stroke_width=0
        )
        safe_zone.move_to(VGroup(
            Dot(line.n2p(0)), Dot(line.n2p(80))
        ).get_center() + UP * 0.2)

        buffer_zone = Rectangle(
            width=line.n2p(82.5)[0] - line.n2p(80)[0],
            height=0.8,
            fill_color=YELLOW, fill_opacity=0.3, stroke_width=0
        )
        buffer_zone.move_to(VGroup(
            Dot(line.n2p(80)), Dot(line.n2p(82.5))
        ).get_center() + UP * 0.2)

        danger_zone = Rectangle(
            width=line.n2p(100)[0] - line.n2p(82.5)[0],
            height=0.8,
            fill_color=RED, fill_opacity=0.2, stroke_width=0
        )
        danger_zone.move_to(VGroup(
            Dot(line.n2p(82.5)), Dot(line.n2p(100))
        ).get_center() + UP * 0.2)

        # Zone labels
        safe_label = Text("Safe to Borrow", font_size=18, color=GREEN, weight=BOLD).move_to(
            safe_zone.get_center() + UP * 0.8
        )
        buffer_label = Text("Buffer", font_size=14, color=YELLOW, weight=BOLD).move_to(
            buffer_zone.get_center() + UP * 0.8
        )
        danger_label = Text("Liquidatable", font_size=18, color=RED, weight=BOLD).move_to(
            danger_zone.get_center() + UP * 0.8
        )

        # Markers
        ltv_arrow = Arrow(
            line.n2p(80) + UP * 1.8, line.n2p(80) + UP * 0.7,
            color=GREEN, buff=0, stroke_width=2
        )
        ltv_text = Text("Max LTV = 80%", font_size=16, color=GREEN).next_to(ltv_arrow, UP, buff=0.1)

        liq_arrow = Arrow(
            line.n2p(82.5) + UP * 1.8, line.n2p(82.5) + UP * 0.7,
            color=RED, buff=0, stroke_width=2
        )
        liq_text = Text("Liq. Threshold = 82.5%", font_size=16, color=RED).next_to(liq_arrow, UP, buff=0.1)

        # Animate
        self.play(Create(line), run_time=1)
        self.play(FadeIn(pct_labels), run_time=0.8)
        self.wait(0.5)

        self.play(FadeIn(safe_zone), Write(safe_label), run_time=0.8)
        self.play(GrowArrow(ltv_arrow), Write(ltv_text), run_time=0.8)
        self.wait(0.5)

        self.play(FadeIn(buffer_zone), Write(buffer_label), run_time=0.8)
        self.play(GrowArrow(liq_arrow), Write(liq_text), run_time=0.8)
        self.wait(0.5)

        self.play(FadeIn(danger_zone), Write(danger_label), run_time=0.8)

        # Explanation
        note = Text(
            "The buffer zone protects borrowers from immediate liquidation",
            font_size=18, color=YELLOW
        ).to_edge(DOWN, buff=0.5)
        self.play(Write(note), run_time=1)
        self.wait(2)
