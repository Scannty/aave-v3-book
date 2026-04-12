from manim import *

class SupplyFlow(Scene):
    """Animated supply flow showing the step-by-step process."""

    def construct(self):
        title = Text("Supply Flow: Pool.supply()", font_size=32, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        steps = [
            ("1", "updateState()", "Update indexes,\naccrue treasury", BLUE),
            ("2", "validateSupply()", "Check active, not paused,\nnot frozen, cap ok", YELLOW),
            ("3", "updateInterestRates()", "Recalculate rates\nwith new liquidity", GREEN),
            ("4", "transferFrom()", "Transfer USDC\nfrom user to aToken", ORANGE),
            ("5", "aToken.mint()", "Mint scaled aTokens\nto user", RED_B),
            ("6", "setAsCollateral()", "Enable as collateral\n(if first supply)", PURPLE),
        ]

        boxes = VGroup()
        arrows = []
        for i, (num, name, desc, color) in enumerate(steps):
            row = i // 2
            col = i % 2

            step_num = Text(num, font_size=28, color=color, weight=BOLD)
            step_name = Text(name, font_size=18, color=WHITE, weight=BOLD)
            step_desc = Text(desc, font_size=14, color=GREY_B)

            content = VGroup(
                VGroup(step_num, step_name).arrange(RIGHT, buff=0.2),
                step_desc,
            ).arrange(DOWN, buff=0.1)

            box = VGroup(
                Rectangle(
                    width=5.5, height=1.3,
                    fill_color=color, fill_opacity=0.1,
                    stroke_color=color, stroke_width=2,
                                    ),
                content,
            )
            content.move_to(box[0])
            box.move_to(
                LEFT * 3 * (1 - 2 * col) + UP * (0.8 - row * 1.6)
            )
            boxes.add(box)

        # Animate step by step
        for i, box in enumerate(boxes):
            self.play(FadeIn(box), run_time=0.8)
            if i < len(boxes) - 1:
                # Draw arrow to next
                next_box = boxes[i + 1]
                if i % 2 == 0:  # left to right
                    arrow = Arrow(
                        box[0].get_right(), next_box[0].get_left(),
                        color=WHITE, buff=0.1, stroke_width=2
                    )
                else:  # right to left (next row)
                    arrow = Arrow(
                        box[0].get_bottom(), next_box[0].get_top(),
                        color=WHITE, buff=0.1, stroke_width=2
                    )
                arrows.append(arrow)
                self.play(GrowArrow(arrow), run_time=0.5)

        self.wait(2)


class BorrowFlow(Scene):
    """Animated borrow flow."""

    def construct(self):
        title = Text("Borrow Flow: Pool.borrow()", font_size=32, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        steps = [
            ("1", "updateState()", "Update indexes", BLUE),
            ("2", "validateBorrow()", "Check collateral,\nHF > 1, caps", YELLOW),
            ("3", "debtToken.mint()", "Mint variable debt\nto borrower", RED_B),
            ("4", "updateInterestRates()", "Rates increase\n(more utilization)", GREEN),
            ("5", "aToken.transferUnderlying()", "Send borrowed asset\nto user", ORANGE),
        ]

        # Vertical flow
        boxes = VGroup()
        for i, (num, name, desc, color) in enumerate(steps):
            step_num = Text(num, font_size=26, color=color, weight=BOLD)
            step_name = Text(name, font_size=18, color=WHITE, weight=BOLD)
            step_desc = Text(desc, font_size=14, color=GREY_B)

            content = VGroup(
                VGroup(step_num, step_name).arrange(RIGHT, buff=0.2),
                step_desc,
            ).arrange(DOWN, buff=0.08)

            box = VGroup(
                Rectangle(
                    width=6, height=1.0,
                    fill_color=color, fill_opacity=0.1,
                    stroke_color=color, stroke_width=2,
                                    ),
                content,
            )
            content.move_to(box[0])
            box.move_to(UP * (2 - i * 1.15))
            boxes.add(box)

        for i, box in enumerate(boxes):
            self.play(FadeIn(box), run_time=0.8)
            if i < len(boxes) - 1:
                arrow = Arrow(
                    box[0].get_bottom(), boxes[i + 1][0].get_top(),
                    color=WHITE, buff=0.05, stroke_width=2
                )
                self.play(GrowArrow(arrow), run_time=0.5)

        self.wait(2)


class RepayWithdrawFlow(Scene):
    """Side-by-side repay and withdraw flows."""

    def construct(self):
        title = Text("Repay & Withdraw Flows", font_size=32, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        # Repay (left)
        repay_title = Text("Repay", font_size=24, color=GREEN, weight=BOLD)
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
                Text(f"{i+1}", font_size=20, color=GREEN, weight=BOLD),
                Text(step, font_size=16, color=GREY_B),
            ).arrange(RIGHT, buff=0.15)
            repay_items.add(item)
        repay_items.arrange(DOWN, aligned_edge=LEFT, buff=0.2)

        repay_box = VGroup(
            Rectangle(width=5, height=4.2, fill_color=GREEN, fill_opacity=0.05, stroke_color=GREEN),
            repay_items,
        )
        repay_items.move_to(repay_box[0])
        repay_box.move_to(LEFT * 3 + DOWN * 0.3)

        # Withdraw (right)
        withdraw_title = Text("Withdraw", font_size=24, color=ORANGE, weight=BOLD)
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
                Text(f"{i+1}", font_size=20, color=ORANGE, weight=BOLD),
                Text(step, font_size=16, color=GREY_B),
            ).arrange(RIGHT, buff=0.15)
            withdraw_items.add(item)
        withdraw_items.arrange(DOWN, aligned_edge=LEFT, buff=0.2)

        withdraw_box = VGroup(
            Rectangle(width=5, height=4.2, fill_color=ORANGE, fill_opacity=0.05, stroke_color=ORANGE),
            withdraw_items,
        )
        withdraw_items.move_to(withdraw_box[0])
        withdraw_box.move_to(RIGHT * 3 + DOWN * 0.3)

        # Animate
        self.play(FadeIn(repay_box), run_time=0.8)
        self.wait(1)
        self.play(FadeIn(withdraw_box), run_time=0.8)
        self.wait(1)

        # Highlight the common pattern
        note = Text(
            "Both start with updateState() and end with updateInterestRates()",
            font_size=18, color=YELLOW
        ).to_edge(DOWN, buff=0.4)
        self.play(Write(note), run_time=1)
        self.wait(2)
