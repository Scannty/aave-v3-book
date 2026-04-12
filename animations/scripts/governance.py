from manim import *

class GovernanceFlow(Scene):
    """Animated governance proposal flow."""

    def construct(self):
        title = Text("Governance Proposal Lifecycle", font_size=32, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        steps = [
            ("Propose", "AAVE holder creates\non-chain proposal", BLUE),
            ("Vote", "Token holders vote\n(3 day period)", PURPLE),
            ("Timelock", "24h delay for\nuser reaction", YELLOW),
            ("Execute", "Payload calls\nPoolConfigurator", GREEN),
            ("Active", "New parameters\ntake effect", RED_B),
        ]

        boxes = VGroup()
        for i, (name, desc, color) in enumerate(steps):
            step_name = Text(name, font_size=22, color=WHITE, weight=BOLD)
            step_desc = Text(desc, font_size=14, color=GREY_B)
            content = VGroup(step_name, step_desc).arrange(DOWN, buff=0.1)

            box = VGroup(
                RoundedRectangle(
                    width=2.2, height=1.5,
                    fill_color=color, fill_opacity=0.15,
                    stroke_color=color, stroke_width=2,
                    corner_radius=0.15,
                ),
                content,
            )
            content.move_to(box[0])
            boxes.add(box)

        boxes.arrange(RIGHT, buff=0.4).move_to(ORIGIN + UP * 0.3)

        # Animate each step
        for i, box in enumerate(boxes):
            self.play(FadeIn(box), run_time=0.8)
            if i < len(boxes) - 1:
                arrow = Arrow(
                    box[0].get_right(), boxes[i + 1][0].get_left(),
                    color=WHITE, buff=0.05, stroke_width=2
                )
                self.play(GrowArrow(arrow), run_time=0.5)

        # Example
        example = Text(
            'Example: setReserveFactor(USDC, 15%) via governance',
            font_size=20, color=YELLOW
        ).to_edge(DOWN, buff=0.6)
        self.play(Write(example), run_time=1)
        self.wait(2)


class ProxyUpgrade(Scene):
    """Animated proxy upgrade diagram."""

    def construct(self):
        title = Text("Proxy Upgrade Architecture", font_size=32, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        # Proxy box
        proxy = VGroup(
            Rectangle(width=4, height=2.5, fill_color=BLUE, fill_opacity=0.15, stroke_color=BLUE, stroke_width=2),
            Text("Pool Proxy", font_size=22, color=BLUE, weight=BOLD).shift(UP * 0.7),
            Text("(address: 0xABC)", font_size=14, color=GREY_B).shift(UP * 0.3),
            Text("Storage lives here", font_size=14, color=GREY_B).shift(DOWN * 0.1),
            Text("delegatecall →", font_size=16, color=YELLOW).shift(DOWN * 0.6),
        )
        proxy.move_to(LEFT * 3)

        # Implementation V1
        impl_v1 = VGroup(
            Rectangle(width=3.5, height=1.5, fill_color=GREEN, fill_opacity=0.15, stroke_color=GREEN, stroke_width=2),
            Text("Implementation V1", font_size=18, color=GREEN, weight=BOLD).shift(UP * 0.2),
            Text("(stateless logic)", font_size=14, color=GREY_B).shift(DOWN * 0.2),
        )
        impl_v1.move_to(RIGHT * 3 + UP * 1)

        # Implementation V2
        impl_v2 = VGroup(
            Rectangle(width=3.5, height=1.5, fill_color=RED_B, fill_opacity=0.15, stroke_color=RED_B, stroke_width=2),
            Text("Implementation V2", font_size=18, color=RED_B, weight=BOLD).shift(UP * 0.2),
            Text("(new features)", font_size=14, color=GREY_B).shift(DOWN * 0.2),
        )
        impl_v2.move_to(RIGHT * 3 + DOWN * 1.5)

        # User
        user = Text("User", font_size=22, color=WHITE, weight=BOLD).move_to(LEFT * 3 + UP * 2.5)
        user_arrow = Arrow(user.get_bottom(), proxy[0].get_top(), color=WHITE, buff=0.1, stroke_width=2)

        # Arrow to V1
        v1_arrow = Arrow(proxy[0].get_right(), impl_v1[0].get_left(), color=GREEN, buff=0.1, stroke_width=2)

        self.play(FadeIn(user), run_time=0.5)
        self.play(FadeIn(proxy), GrowArrow(user_arrow), run_time=1)
        self.play(FadeIn(impl_v1), GrowArrow(v1_arrow), run_time=1)
        self.wait(1)

        # Governance triggers upgrade
        gov_text = Text("Governance calls\nsetPoolImpl(V2)", font_size=16, color=YELLOW).move_to(ORIGIN + DOWN * 3.2)
        self.play(Write(gov_text), run_time=0.8)

        # Cross out V1 arrow, show V2
        cross = Cross(v1_arrow, stroke_color=RED, stroke_width=3)
        self.play(Create(cross), run_time=0.8)

        v2_arrow = Arrow(proxy[0].get_right(), impl_v2[0].get_left(), color=RED_B, buff=0.1, stroke_width=2)
        self.play(FadeIn(impl_v2), GrowArrow(v2_arrow), run_time=1)

        # Note
        note = Text("Same address, same storage, new logic", font_size=18, color=GREEN).to_edge(DOWN, buff=0.3)
        self.play(Write(note), run_time=0.8)
        self.wait(2)


class PortalDiagram(Scene):
    """Animated Portal cross-chain flow."""

    def construct(self):
        title = Text("Portal: Cross-Chain Liquidity", font_size=32, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        # Chain A (left)
        chain_a = VGroup(
            Rectangle(width=4.5, height=3.5, fill_color=BLUE, fill_opacity=0.1, stroke_color=BLUE),
            Text("Chain A", font_size=22, color=BLUE, weight=BOLD).shift(UP * 1.3),
        )
        chain_a.move_to(LEFT * 3.5 + DOWN * 0.3)

        # Chain B (right)
        chain_b = VGroup(
            Rectangle(width=4.5, height=3.5, fill_color=GREEN, fill_opacity=0.1, stroke_color=GREEN),
            Text("Chain B", font_size=22, color=GREEN, weight=BOLD).shift(UP * 1.3),
        )
        chain_b.move_to(RIGHT * 3.5 + DOWN * 0.3)

        self.play(FadeIn(chain_a), FadeIn(chain_b), run_time=0.8)

        # Steps on chain A
        step1 = Text("1. User wants to move\n   1000 aUSDC", font_size=14, color=GREY_B).move_to(LEFT * 3.5 + UP * 0.3)
        step2 = Text("2. Bridge burns\n   user's aUSDC", font_size=14, color=RED_B).move_to(LEFT * 3.5 + DOWN * 0.6)
        step5 = Text("5. Bridge transfers\n   real USDC", font_size=14, color=ORANGE).move_to(LEFT * 3.5 + DOWN * 1.5)

        # Steps on chain B
        step3 = Text("3. mintUnbacked()\n   on Pool", font_size=14, color=GREEN).move_to(RIGHT * 3.5 + UP * 0.3)
        step4 = Text("4. User receives\n   unbacked aUSDC", font_size=14, color=GREY_B).move_to(RIGHT * 3.5 + DOWN * 0.6)
        step6 = Text("6. backUnbacked()\n   backs the mint", font_size=14, color=YELLOW).move_to(RIGHT * 3.5 + DOWN * 1.5)

        # Message arrow
        msg_arrow = Arrow(LEFT * 1, RIGHT * 1, color=YELLOW, buff=0, stroke_width=2).shift(UP * 0.3)
        msg_label = Text("message", font_size=14, color=YELLOW).next_to(msg_arrow, UP, buff=0.05)

        bridge_arrow = Arrow(LEFT * 1, RIGHT * 1, color=ORANGE, buff=0, stroke_width=2).shift(DOWN * 1.5)
        bridge_label = Text("bridge", font_size=14, color=ORANGE).next_to(bridge_arrow, UP, buff=0.05)

        # Animate steps
        self.play(Write(step1), run_time=0.8)
        self.play(Write(step2), run_time=0.8)
        self.play(GrowArrow(msg_arrow), Write(msg_label), run_time=1)
        self.play(Write(step3), run_time=0.8)
        self.play(Write(step4), run_time=0.8)
        self.play(Write(step5), run_time=0.8)
        self.play(GrowArrow(bridge_arrow), Write(bridge_label), run_time=1)
        self.play(Write(step6), run_time=0.8)
        self.wait(2)
