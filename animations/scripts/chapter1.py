from manim import *

class EconomicLoop(Scene):
    """Animated flow showing how money moves through Aave."""

    def construct(self):
        title = Text("The Aave Economic Loop", font_size=34, color=WHITE).to_edge(UP, buff=0.3)
        self.play(FadeIn(title), run_time=1)

        # Three nodes in a row
        supplier = VGroup(
            Circle(radius=0.8, fill_color=GREEN, fill_opacity=0.2, stroke_color=GREEN, stroke_width=2),
            Text("Suppliers", font_size=18, color=GREEN, weight=BOLD),
        )
        supplier[1].move_to(supplier[0])
        supplier.move_to(LEFT * 4.5 + UP * 0.5)

        pool = VGroup(
            Circle(radius=1.0, fill_color=BLUE, fill_opacity=0.2, stroke_color=BLUE, stroke_width=2),
            Text("Pool", font_size=20, color=BLUE, weight=BOLD),
        )
        pool[1].move_to(pool[0])
        pool.move_to(ORIGIN + UP * 0.5)

        borrower = VGroup(
            Circle(radius=0.8, fill_color=RED_B, fill_opacity=0.2, stroke_color=RED_B, stroke_width=2),
            Text("Borrowers", font_size=18, color=RED_B, weight=BOLD),
        )
        borrower[1].move_to(borrower[0])
        borrower.move_to(RIGHT * 4.5 + UP * 0.5)

        treasury = VGroup(
            Circle(radius=0.65, fill_color=YELLOW, fill_opacity=0.2, stroke_color=YELLOW, stroke_width=2),
            Text("Treasury", font_size=16, color=YELLOW, weight=BOLD),
        )
        treasury[1].move_to(treasury[0])
        treasury.move_to(ORIGIN + DOWN * 2.3)

        # Show all nodes
        self.play(FadeIn(supplier), FadeIn(pool), FadeIn(borrower), run_time=1)
        self.wait(0.5)

        # Left side: two straight horizontal arrows
        y_top = UP * 0.8
        y_bot = UP * 0.2

        arr1 = Arrow(supplier[0].get_right() + y_top, pool[0].get_left() + y_top, color=GREEN, buff=0.05, stroke_width=3)
        lbl1 = Text("Deposit assets", font_size=15, color=GREEN).next_to(arr1, UP, buff=0.1)
        self.play(GrowArrow(arr1), FadeIn(lbl1), run_time=1)

        arr2 = Arrow(pool[0].get_left() + y_bot, supplier[0].get_right() + y_bot, color=GREEN_B, buff=0.05, stroke_width=3)
        lbl2 = Text("Earn interest", font_size=15, color=GREEN_B).next_to(arr2, DOWN, buff=0.1)
        self.play(GrowArrow(arr2), FadeIn(lbl2), run_time=1)
        self.wait(0.3)

        # Right side: two straight horizontal arrows
        arr3 = Arrow(pool[0].get_right() + y_top, borrower[0].get_left() + y_top, color=BLUE, buff=0.05, stroke_width=3)
        lbl3 = Text("Loan assets", font_size=15, color=BLUE).next_to(arr3, UP, buff=0.1)
        self.play(GrowArrow(arr3), FadeIn(lbl3), run_time=1)

        arr4 = Arrow(borrower[0].get_left() + y_bot, pool[0].get_right() + y_bot, color=RED_B, buff=0.05, stroke_width=3)
        lbl4 = Text("Pay interest", font_size=15, color=RED_B).next_to(arr4, DOWN, buff=0.1)
        self.play(GrowArrow(arr4), FadeIn(lbl4), run_time=1)
        self.wait(0.5)

        # Treasury: straight down from pool
        self.play(FadeIn(treasury), run_time=0.5)
        arr5 = Arrow(pool[0].get_bottom(), treasury[0].get_top(), color=YELLOW, buff=0.05, stroke_width=3)
        lbl5 = Text("Protocol fee (10-20%)", font_size=15, color=YELLOW).next_to(arr5, RIGHT, buff=0.15)
        self.play(GrowArrow(arr5), FadeIn(lbl5), run_time=1)

        # Summary
        summary = Text(
            "Borrowers pay  ->  Suppliers earn  ->  Protocol keeps a cut",
            font_size=20, color=GREY_B
        ).to_edge(DOWN, buff=0.4)
        self.play(FadeIn(summary), run_time=1)
        self.wait(2)


class UnifiedPool(Scene):
    """Shows multiple assets flowing into one unified pool with suppliers and borrowers."""

    def construct(self):
        title = Text("The Unified Pool", font_size=34, color=WHITE).to_edge(UP, buff=0.3)
        self.play(FadeIn(title), run_time=1)

        # The pool in the center
        pool_rect = Rectangle(
            width=3.5, height=4,
            fill_color=BLUE, fill_opacity=0.1,
            stroke_color=BLUE, stroke_width=2,
        )
        pool_rect.move_to(ORIGIN + DOWN * 0.2)
        pool_label = Text("Aave V3 Pool", font_size=20, color=BLUE, weight=BOLD).move_to(pool_rect.get_center() + DOWN * 1.5)

        self.play(FadeIn(pool_rect), FadeIn(pool_label), run_time=1)

        # Asset tokens inside the pool
        asset_names = ["ETH", "USDC", "WBTC", "DAI"]
        asset_colors = [BLUE_B, TEAL, ORANGE, YELLOW]
        positions = [UP * 1.0 + LEFT * 0.6, UP * 1.0 + RIGHT * 0.6,
                     UP * 0.0 + LEFT * 0.6, UP * 0.0 + RIGHT * 0.6]

        asset_dots = VGroup()
        for name, color, pos in zip(asset_names, asset_colors, positions):
            dot = VGroup(
                Circle(radius=0.35, fill_color=color, fill_opacity=0.3, stroke_color=color, stroke_width=2),
                Text(name, font_size=14, color=WHITE, weight=BOLD),
            )
            dot[1].move_to(dot[0])
            dot.move_to(pool_rect.get_center() + pos + UP * 0.3)
            asset_dots.add(dot)

        self.play(*[FadeIn(d) for d in asset_dots], run_time=1)
        self.wait(0.5)

        # Suppliers on the left
        supplier_label = Text("Suppliers", font_size=22, color=GREEN, weight=BOLD).move_to(LEFT * 5 + UP * 1.5)
        suppliers = VGroup()
        for i in range(3):
            s = VGroup(
                Circle(radius=0.25, fill_color=GREEN, fill_opacity=0.2, stroke_color=GREEN),
                Text(f"User {i+1}", font_size=10, color=GREEN),
            )
            s[1].move_to(s[0])
            s.move_to(LEFT * 5 + UP * (0.5 - i * 0.8))
            suppliers.add(s)

        self.play(FadeIn(supplier_label), *[FadeIn(s) for s in suppliers], run_time=0.8)

        # Borrowers on the right
        borrower_label = Text("Borrowers", font_size=22, color=RED_B, weight=BOLD).move_to(RIGHT * 5 + UP * 1.5)
        borrowers = VGroup()
        for i in range(3):
            b = VGroup(
                Circle(radius=0.25, fill_color=RED_B, fill_opacity=0.2, stroke_color=RED_B),
                Text(f"User {chr(65+i)}", font_size=10, color=RED_B),
            )
            b[1].move_to(b[0])
            b.move_to(RIGHT * 5 + UP * (0.5 - i * 0.8))
            borrowers.add(b)

        self.play(FadeIn(borrower_label), *[FadeIn(b) for b in borrowers], run_time=0.8)
        self.wait(0.3)

        # LEFT SIDE: two straight horizontal arrows
        y_top = UP * 0.3
        y_bot = DOWN * 0.5

        # Arrow 1: Suppliers → Pool (deposit)
        deposit_arrow = Arrow(LEFT * 3.8 + y_top, pool_rect.get_left() + y_top, color=GREEN, buff=0.05, stroke_width=3)
        deposit_label = Text("Deposit assets", font_size=15, color=GREEN).next_to(deposit_arrow, UP, buff=0.1)
        self.play(GrowArrow(deposit_arrow), FadeIn(deposit_label), run_time=1)

        # Arrow 2: Pool → Suppliers (aTokens back)
        atoken_arrow = Arrow(pool_rect.get_left() + y_bot, LEFT * 3.8 + y_bot, color=GREEN_B, buff=0.05, stroke_width=3)
        atoken_label = Text("Receive aTokens", font_size=15, color=GREEN_B).next_to(atoken_arrow, DOWN, buff=0.1)
        self.play(GrowArrow(atoken_arrow), FadeIn(atoken_label), run_time=1)
        self.wait(0.3)

        # RIGHT SIDE: two straight horizontal arrows
        # Arrow 3: Pool → Borrowers (loan)
        loan_arrow = Arrow(pool_rect.get_right() + y_top, RIGHT * 3.8 + y_top, color=RED_B, buff=0.05, stroke_width=3)
        loan_label = Text("Borrow assets", font_size=15, color=RED_B).next_to(loan_arrow, UP, buff=0.1)
        self.play(GrowArrow(loan_arrow), FadeIn(loan_label), run_time=1)

        # Arrow 4: Borrowers → Pool (collateral)
        collateral_arrow = Arrow(RIGHT * 3.8 + y_bot, pool_rect.get_right() + y_bot, color=ORANGE, buff=0.05, stroke_width=3)
        collateral_label = Text("Post collateral", font_size=15, color=ORANGE).next_to(collateral_arrow, DOWN, buff=0.1)
        self.play(GrowArrow(collateral_arrow), FadeIn(collateral_label), run_time=1)

        self.wait(2)
