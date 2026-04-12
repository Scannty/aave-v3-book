from manim import *

class ArchitectureDiagram(Scene):
    """Animated architecture diagram showing Aave V3 contract relationships."""

    def construct(self):
        title = Text("Aave V3 Contract Architecture", font_size=34, color=WHITE).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=1)

        # Pool box (center)
        pool = VGroup(
            Rectangle(width=2.5, height=0.8, fill_color=BLUE, fill_opacity=0.3, stroke_color=BLUE),
            Text("Pool.sol", font_size=20, color=WHITE, weight=BOLD),
        )
        pool[1].move_to(pool[0])
        pool.move_to(ORIGIN + UP * 1.5)

        # Library boxes (left side)
        libs = []
        lib_names = ["SupplyLogic", "BorrowLogic", "LiquidationLogic", "FlashLoanLogic", "EModeLogic"]
        for i, name in enumerate(lib_names):
            box = VGroup(
                Rectangle(width=2.2, height=0.55, fill_color=GREEN, fill_opacity=0.2, stroke_color=GREEN),
                Text(name, font_size=14, color=GREEN),
            )
            box[1].move_to(box[0])
            box.move_to(LEFT * 4.5 + UP * (1.5 - i * 0.75))
            libs.append(box)

        # Validation + Reserve (below libs)
        validation = VGroup(
            Rectangle(width=2.2, height=0.55, fill_color=YELLOW, fill_opacity=0.2, stroke_color=YELLOW),
            Text("ValidationLogic", font_size=14, color=YELLOW),
        )
        validation[1].move_to(validation[0])
        validation.move_to(LEFT * 4.5 + DOWN * 2.2)

        reserve = VGroup(
            Rectangle(width=2.2, height=0.55, fill_color=YELLOW, fill_opacity=0.2, stroke_color=YELLOW),
            Text("ReserveLogic", font_size=14, color=YELLOW),
        )
        reserve[1].move_to(reserve[0])
        reserve.move_to(LEFT * 4.5 + DOWN * 3)

        # Token boxes (right side)
        tokens = []
        token_names = ["aToken", "VariableDebtToken", "StableDebtToken"]
        token_colors = [BLUE_B, RED_B, ORANGE]
        for i, (name, col) in enumerate(zip(token_names, token_colors)):
            box = VGroup(
                Rectangle(width=2.4, height=0.55, fill_color=col, fill_opacity=0.2, stroke_color=col),
                Text(name, font_size=14, color=col),
            )
            box[1].move_to(box[0])
            box.move_to(RIGHT * 4.5 + UP * (1.5 - i * 0.75))
            tokens.append(box)

        # Oracle + ACL (right bottom)
        oracle = VGroup(
            Rectangle(width=2.4, height=0.55, fill_color=PURPLE, fill_opacity=0.2, stroke_color=PURPLE),
            Text("AaveOracle", font_size=14, color=PURPLE),
        )
        oracle[1].move_to(oracle[0])
        oracle.move_to(RIGHT * 4.5 + DOWN * 0.5)

        acl = VGroup(
            Rectangle(width=2.4, height=0.55, fill_color=GREY_B, fill_opacity=0.2, stroke_color=GREY_B),
            Text("ACLManager", font_size=14, color=GREY_B),
        )
        acl[1].move_to(acl[0])
        acl.move_to(RIGHT * 4.5 + DOWN * 1.3)

        # PoolConfigurator (bottom center)
        configurator = VGroup(
            Rectangle(width=2.8, height=0.8, fill_color=TEAL, fill_opacity=0.3, stroke_color=TEAL),
            Text("PoolConfigurator", font_size=18, color=WHITE, weight=BOLD),
        )
        configurator[1].move_to(configurator[0])
        configurator.move_to(ORIGIN + DOWN * 2.2)

        # AddressesProvider (bottom)
        provider = VGroup(
            Rectangle(width=3.2, height=0.8, fill_color=MAROON, fill_opacity=0.3, stroke_color=MAROON),
            Text("AddressesProvider", font_size=18, color=WHITE, weight=BOLD),
        )
        provider[1].move_to(provider[0])
        provider.move_to(ORIGIN + DOWN * 3.5)

        # User
        user = Text("User", font_size=22, color=WHITE, weight=BOLD).move_to(ORIGIN + UP * 2.8)

        # Arrows
        user_arrow = Arrow(user.get_bottom(), pool[0].get_top(), color=WHITE, buff=0.1, stroke_width=2)

        # Animate: User -> Pool
        self.play(FadeIn(user), run_time=0.5)
        self.play(FadeIn(pool), GrowArrow(user_arrow), run_time=1)

        # Pool -> Libraries
        lib_arrows = []
        for lib in libs:
            arrow = Arrow(pool[0].get_left(), lib[0].get_right(), color=GREEN, buff=0.1, stroke_width=2)
            lib_arrows.append(arrow)

        self.play(
            *[FadeIn(lib) for lib in libs],
            *[GrowArrow(a) for a in lib_arrows],
            run_time=1.5
        )

        # Libraries -> Validation -> Reserve
        val_arrow = Arrow(libs[2][0].get_bottom(), validation[0].get_top(), color=YELLOW, buff=0.1, stroke_width=2)
        res_arrow = Arrow(validation[0].get_bottom(), reserve[0].get_top(), color=YELLOW, buff=0.1, stroke_width=2)
        self.play(FadeIn(validation), GrowArrow(val_arrow), run_time=0.8)
        self.play(FadeIn(reserve), GrowArrow(res_arrow), run_time=0.8)

        # Pool -> Tokens
        token_arrows = []
        for tok in tokens:
            arrow = Arrow(pool[0].get_right(), tok[0].get_left(), color=BLUE_B, buff=0.1, stroke_width=2)
            token_arrows.append(arrow)

        self.play(
            *[FadeIn(tok) for tok in tokens],
            *[GrowArrow(a) for a in token_arrows],
            run_time=1.5
        )

        # Oracle + ACL
        oracle_arrow = Arrow(pool[0].get_right() + DOWN * 0.2, oracle[0].get_left(), color=PURPLE, buff=0.1, stroke_width=2)
        acl_arrow = Arrow(pool[0].get_right() + DOWN * 0.3, acl[0].get_left(), color=GREY_B, buff=0.1, stroke_width=2)
        self.play(
            FadeIn(oracle), GrowArrow(oracle_arrow),
            FadeIn(acl), GrowArrow(acl_arrow),
            run_time=1
        )

        # Configurator + Provider
        conf_arrow = Arrow(configurator[0].get_top(), pool[0].get_bottom(), color=TEAL, buff=0.1, stroke_width=2)
        prov_arrow1 = Arrow(provider[0].get_top(), configurator[0].get_bottom(), color=MAROON, buff=0.1, stroke_width=2)

        self.play(FadeIn(configurator), GrowArrow(conf_arrow), run_time=1)
        self.play(FadeIn(provider), GrowArrow(prov_arrow1), run_time=1)

        # Labels
        lib_label = Text("Libraries", font_size=16, color=GREEN, weight=BOLD).next_to(libs[0], UP, buff=0.15)
        token_label = Text("Per-Asset Tokens", font_size=16, color=BLUE_B, weight=BOLD).next_to(tokens[0], UP, buff=0.15)
        self.play(Write(lib_label), Write(token_label), run_time=0.8)

        self.wait(2)
