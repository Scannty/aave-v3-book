from manim import *

class ArchitectureDiagram(Scene):
    """Animated architecture diagram showing Aave V3 contract relationships."""

    def construct(self):
        self.camera.background_color = BLACK

        title = Text("Aave V3 Contract Architecture", font_size=40, color=WHITE).to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=1)

        def make_box(name, width=2.4, height=0.6):
            box = VGroup(
                RoundedRectangle(
                    width=width, height=height, corner_radius=0.1,
                    fill_color=WHITE, fill_opacity=0.05,
                    stroke_color=GREY, stroke_width=1,
                ),
                Text(name, font_size=16, color=WHITE),
            )
            box[1].move_to(box[0])
            return box

        def make_arrow(start, end):
            return Arrow(start, end, color=GREY, buff=0.08, stroke_width=1.5, max_tip_length_to_length_ratio=0.15)

        # Pool box (center)
        pool = make_box("Pool.sol", width=2.8, height=0.8)
        pool[1] = Text("Pool.sol", font_size=22, color=WHITE, weight=BOLD)
        pool[1].move_to(pool[0])
        pool.move_to(ORIGIN + UP * 1.5)

        # Library boxes (left side)
        lib_names = ["SupplyLogic", "BorrowLogic", "LiquidationLogic", "FlashLoanLogic", "EModeLogic", "ValidationLogic", "ReserveLogic"]
        libs = []
        for i, name in enumerate(lib_names):
            box = make_box(name)
            box.move_to(LEFT * 4.5 + UP * (2.0 - i * 0.8))
            libs.append(box)

        # Token boxes (right side)
        token_names = ["aToken", "VariableDebtToken", "StableDebtToken", "AaveOracle", "ACLManager"]
        tokens = []
        for i, name in enumerate(token_names):
            box = make_box(name)
            box.move_to(RIGHT * 4.5 + UP * (2.0 - i * 0.8))
            tokens.append(box)

        # PoolConfigurator (bottom center)
        configurator = make_box("PoolConfigurator", width=3.0, height=0.7)
        configurator[1] = Text("PoolConfigurator", font_size=18, color=WHITE, weight=BOLD)
        configurator[1].move_to(configurator[0])
        configurator.move_to(ORIGIN + DOWN * 1.8)

        # AddressesProvider (bottom)
        provider = make_box("AddressesProvider", width=3.2, height=0.7)
        provider[1] = Text("AddressesProvider", font_size=18, color=WHITE, weight=BOLD)
        provider[1].move_to(provider[0])
        provider.move_to(ORIGIN + DOWN * 3.2)

        # User
        user = Text("User", font_size=22, color=WHITE, weight=BOLD).move_to(ORIGIN + UP * 2.8)

        # Animate: User -> Pool
        user_arrow = make_arrow(user.get_bottom(), pool[0].get_top())
        self.play(FadeIn(user), run_time=0.5)
        self.play(FadeIn(pool), GrowArrow(user_arrow), run_time=1)

        # Pool -> Libraries
        lib_arrows = [make_arrow(pool[0].get_left(), lib[0].get_right()) for lib in libs]
        self.play(
            *[FadeIn(lib) for lib in libs],
            *[GrowArrow(a) for a in lib_arrows],
            run_time=1.5
        )

        # Labels
        lib_label = Text("Libraries", font_size=16, color=GREY_B, weight=BOLD).next_to(libs[0], UP, buff=0.15)
        self.play(Write(lib_label), run_time=0.5)

        # Pool -> Tokens
        token_arrows = [make_arrow(pool[0].get_right(), tok[0].get_left()) for tok in tokens]
        self.play(
            *[FadeIn(tok) for tok in tokens],
            *[GrowArrow(a) for a in token_arrows],
            run_time=1.5
        )

        token_label = Text("Per-Asset Contracts", font_size=16, color=GREY_B, weight=BOLD).next_to(tokens[0], UP, buff=0.15)
        self.play(Write(token_label), run_time=0.5)

        # Configurator + Provider
        conf_arrow = make_arrow(configurator[0].get_top(), pool[0].get_bottom())
        prov_arrow = make_arrow(provider[0].get_top(), configurator[0].get_bottom())

        self.play(FadeIn(configurator), GrowArrow(conf_arrow), run_time=1)
        self.play(FadeIn(provider), GrowArrow(prov_arrow), run_time=1)

        self.wait(2)
