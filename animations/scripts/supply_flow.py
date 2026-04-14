from manim import *

class SupplyFlow(Scene):
    """Animated supply flow showing the step-by-step process."""

    def construct(self):
        self.camera.background_color = BLACK

        title = Text("Supply Flow: Pool.supply()", font_size=40, color=WHITE).to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1)

        steps = [
            ("1", "updateState()", "Update indexes, accrue treasury"),
            ("2", "validateSupply()", "Check active, not paused, not frozen, cap ok"),
            ("3", "updateInterestRates()", "Recalculate rates with new liquidity"),
            ("4", "transferFrom()", "Transfer USDC from user to aToken"),
            ("5", "aToken.mint()", "Mint scaled aTokens to user"),
            ("6", "setAsCollateral()", "Enable as collateral (if first supply)"),
        ]

        boxes = VGroup()
        for i, (num, name, desc) in enumerate(steps):
            step_num = Text(num, font_size=28, color=WHITE, weight=BOLD)
            step_name = Text(name, font_size=22, color=WHITE, weight=BOLD)
            step_desc = Text(desc, font_size=16, color=GREY_B)

            content = VGroup(
                VGroup(step_num, step_name).arrange(RIGHT, buff=0.2),
                step_desc,
            ).arrange(DOWN, buff=0.1)

            box = VGroup(
                RoundedRectangle(
                    width=9, height=1.0, corner_radius=0.15,
                    fill_color=WHITE, fill_opacity=0.05,
                    stroke_color=GREY, stroke_width=1,
                ),
                content,
            )
            content.move_to(box[0])
            box.move_to(UP * (2.0 - i * 0.95))
            boxes.add(box)

        for i, box in enumerate(boxes):
            self.play(FadeIn(box), run_time=0.7)
            if i < len(boxes) - 1:
                arrow = Arrow(
                    box[0].get_bottom(), boxes[i + 1][0].get_top(),
                    color=GREY, buff=0.05, stroke_width=2,
                    max_tip_length_to_length_ratio=0.25,
                )
                self.play(GrowArrow(arrow), run_time=0.4)

        self.wait(2)


class BorrowFlow(Scene):
    """Animated borrow flow."""

    def construct(self):
        self.camera.background_color = BLACK

        title = Text("Borrow Flow: Pool.borrow()", font_size=40, color=WHITE).to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1)

        steps = [
            ("1", "updateState()", "Update indexes"),
            ("2", "validateBorrow()", "Check collateral, HF > 1, caps"),
            ("3", "debtToken.mint()", "Mint variable debt to borrower"),
            ("4", "updateInterestRates()", "Rates increase (more utilization)"),
            ("5", "aToken.transferUnderlying()", "Send borrowed asset to user"),
        ]

        boxes = VGroup()
        for i, (num, name, desc) in enumerate(steps):
            step_num = Text(num, font_size=28, color=WHITE, weight=BOLD)
            step_name = Text(name, font_size=22, color=WHITE, weight=BOLD)
            step_desc = Text(desc, font_size=16, color=GREY_B)

            content = VGroup(
                VGroup(step_num, step_name).arrange(RIGHT, buff=0.2),
                step_desc,
            ).arrange(DOWN, buff=0.1)

            box = VGroup(
                RoundedRectangle(
                    width=9, height=1.0, corner_radius=0.15,
                    fill_color=WHITE, fill_opacity=0.05,
                    stroke_color=GREY, stroke_width=1,
                ),
                content,
            )
            content.move_to(box[0])
            box.move_to(UP * (2.0 - i * 1.1))
            boxes.add(box)

        for i, box in enumerate(boxes):
            self.play(FadeIn(box), run_time=0.7)
            if i < len(boxes) - 1:
                arrow = Arrow(
                    box[0].get_bottom(), boxes[i + 1][0].get_top(),
                    color=GREY, buff=0.05, stroke_width=2,
                    max_tip_length_to_length_ratio=0.25,
                )
                self.play(GrowArrow(arrow), run_time=0.4)

        self.wait(2)


class RepayWithdrawFlow(Scene):
    """Side-by-side repay and withdraw flows."""

    def construct(self):
        self.camera.background_color = BLACK

        title = Text("Repay & Withdraw Flows", font_size=40, color=WHITE).to_edge(UP, buff=0.5)
        self.play(Write(title), run_time=1)

        # Repay (left)
        repay_title = Text("Repay", font_size=26, color=WHITE, weight=BOLD)
        repay_steps = [
            "updateState()",
            "Calculate repay amount",
            "debtToken.burn()",
            "Transfer USDC to aToken",
            "updateInterestRates()",
        ]

        repay_items = VGroup(repay_title)
        for i, step in enumerate(repay_steps):
            item = VGroup(
                Text(f"{i+1}", font_size=20, color=WHITE, weight=BOLD),
                Text(step, font_size=16, color=GREY_B),
            ).arrange(RIGHT, buff=0.15)
            repay_items.add(item)
        repay_items.arrange(DOWN, aligned_edge=LEFT, buff=0.25)

        repay_box = VGroup(
            RoundedRectangle(
                width=5.5, height=4.5, corner_radius=0.15,
                fill_color=WHITE, fill_opacity=0.05,
                stroke_color=GREY, stroke_width=1,
            ),
            repay_items,
        )
        repay_items.move_to(repay_box[0])
        repay_box.move_to(LEFT * 3.2 + DOWN * 0.3)

        # Withdraw (right)
        withdraw_title = Text("Withdraw", font_size=26, color=WHITE, weight=BOLD)
        withdraw_steps = [
            "updateState()",
            "Validate HF stays > 1",
            "aToken.burn()",
            "Transfer underlying to user",
            "updateInterestRates()",
        ]

        withdraw_items = VGroup(withdraw_title)
        for i, step in enumerate(withdraw_steps):
            item = VGroup(
                Text(f"{i+1}", font_size=20, color=WHITE, weight=BOLD),
                Text(step, font_size=16, color=GREY_B),
            ).arrange(RIGHT, buff=0.15)
            withdraw_items.add(item)
        withdraw_items.arrange(DOWN, aligned_edge=LEFT, buff=0.25)

        withdraw_box = VGroup(
            RoundedRectangle(
                width=5.5, height=4.5, corner_radius=0.15,
                fill_color=WHITE, fill_opacity=0.05,
                stroke_color=GREY, stroke_width=1,
            ),
            withdraw_items,
        )
        withdraw_items.move_to(withdraw_box[0])
        withdraw_box.move_to(RIGHT * 3.2 + DOWN * 0.3)

        # Animate
        self.play(FadeIn(repay_box), run_time=0.8)
        self.wait(1)
        self.play(FadeIn(withdraw_box), run_time=0.8)
        self.wait(1)

        note = Text(
            "Both start with updateState() and end with updateInterestRates()",
            font_size=18, color=GREY_B
        ).to_edge(DOWN, buff=0.4)
        self.play(Write(note), run_time=1)
        self.wait(2)
