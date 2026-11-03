import os
import tempfile
from PIL import Image
from backend.image_generator import generate_menu_card


def test_generate_menu_card_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test_menu.png")
        img = generate_menu_card(
            title="Kürbissuppe",
            subtitle="mit gerösteten Kürbiskernen",
            price="6,90 €",
            badge="HEUTE EMPFOHLEN",
            output_path=out_path,
        )

        assert os.path.exists(out_path)
        assert img.size == (800, 480)

        # Verify it can be opened by PIL
        with Image.open(out_path) as loaded:
            assert loaded.format == "PNG"
            assert loaded.size == (800, 480)


def test_generate_menu_card_with_dithering():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test_dither.png")
        img = generate_menu_card(
            title="Wiener Schnitzel",
            subtitle="mit Erdäpfelsalat",
            price="18,50 €",
            version=42,
            dither_eink=True,
            output_path=out_path,
        )

        assert os.path.exists(out_path)
        assert img.size == (800, 480)


def test_generate_long_text_wrapping():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test_long.png")
        img = generate_menu_card(
            title="Hausgemachte Minz-Zitronen-Ingwer Limonade",
            subtitle="Frisch zubereitet mit Rohrzucker aus fairem Handel und prickelndem Quellwasser",
            price="4,50 €",
            output_path=out_path,
        )
        assert os.path.exists(out_path)
