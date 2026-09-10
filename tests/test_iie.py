"""
Tests de la matriz de riesgo y de la geometría de alertas.

Correr:  python -m pytest tests/ -v      (o  python tests/test_iie.py)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, iie, smn  # noqa: E402


class TestSaturacion(unittest.TestCase):
    """La conversión m³/m³ -> % de saturación es el punto más delicado."""

    def test_equivalencias_de_la_matriz(self):
        # Los umbrales en m³/m³ deben derivarse de la porosidad configurada.
        # Con la calibración vigente (0.53): 60 % -> 0.318 y 75 % -> 0.398
        u60 = config.SATURACION_AMARILLO_PCT / 100 * config.POROSIDAD_TOTAL
        u75 = config.SATURACION_ROJO_PCT / 100 * config.POROSIDAD_TOTAL
        self.assertAlmostEqual(iie.saturacion_pct(u60), 60.0, places=1)
        self.assertAlmostEqual(iie.saturacion_pct(u75), 75.0, places=1)

    def test_calibracion_vigente(self):
        # Blindaje: si alguien cambia la porosidad sin querer, esto lo avisa.
        self.assertAlmostEqual(config.POROSIDAD_TOTAL, 0.53, places=2)

    def test_suelo_seco(self):
        self.assertLess(iie.saturacion_pct(0.10), 30.0)

    def test_tope_en_100(self):
        self.assertEqual(iie.saturacion_pct(0.80), 100.0)

    def test_none_no_rompe(self):
        self.assertIsNone(iie.saturacion_pct(None))


class TestNivelCategorico(unittest.TestCase):

    def test_verde(self):
        r = iie.nivel_categorico(precip_mm=1.0, saturacion=45.0)
        self.assertEqual(r["nivel"], "verde")

    def test_amarillo_por_lluvia(self):
        r = iie.nivel_categorico(precip_mm=5.0, saturacion=40.0)
        self.assertEqual(r["nivel"], "amarillo")

    def test_amarillo_por_suelo(self):
        r = iie.nivel_categorico(precip_mm=0.5, saturacion=68.0)
        self.assertEqual(r["nivel"], "amarillo")

    def test_rojo_por_lluvia(self):
        r = iie.nivel_categorico(precip_mm=7.1, saturacion=30.0)
        self.assertEqual(r["nivel"], "rojo")

    def test_rojo_por_suelo(self):
        r = iie.nivel_categorico(precip_mm=0.0, saturacion=80.0)
        self.assertEqual(r["nivel"], "rojo")

    def test_bordes_exactos(self):
        # 3.0 mm entra en amarillo; 2.99 sigue verde
        self.assertEqual(iie.nivel_categorico(3.0, 10.0)["nivel"], "amarillo")
        self.assertEqual(iie.nivel_categorico(2.99, 10.0)["nivel"], "verde")
        # 7.0 mm sigue amarillo (rojo es ESTRICTAMENTE mayor); 7.01 es rojo
        self.assertEqual(iie.nivel_categorico(7.0, 10.0)["nivel"], "amarillo")
        self.assertEqual(iie.nivel_categorico(7.01, 10.0)["nivel"], "rojo")
        # 60 % entra en amarillo; 75 % sigue amarillo; 75.1 % es rojo
        self.assertEqual(iie.nivel_categorico(0.0, 60.0)["nivel"], "amarillo")
        self.assertEqual(iie.nivel_categorico(0.0, 75.0)["nivel"], "amarillo")
        self.assertEqual(iie.nivel_categorico(0.0, 75.1)["nivel"], "rojo")

    def test_alerta_smn_naranja_fuerza_rojo(self):
        r = iie.nivel_categorico(0.0, 20.0, color_smn="naranja")
        self.assertEqual(r["nivel"], "rojo")

    def test_alerta_smn_roja_fuerza_rojo(self):
        r = iie.nivel_categorico(0.0, 20.0, color_smn="rojo")
        self.assertEqual(r["nivel"], "rojo")

    def test_alerta_smn_amarilla_eleva_verde_a_amarillo(self):
        r = iie.nivel_categorico(0.0, 20.0, color_smn="amarillo")
        self.assertEqual(r["nivel"], "amarillo")

    def test_sin_dato_de_suelo_no_rompe(self):
        r = iie.nivel_categorico(1.0, None)
        self.assertEqual(r["nivel"], "verde")

    def test_disparadores_se_documentan(self):
        r = iie.nivel_categorico(9.0, 80.0, color_smn="rojo")
        self.assertEqual(len(r["disparadores"]), 3)


class TestIIEContinuo(unittest.TestCase):

    def test_cero_en_condiciones_secas(self):
        self.assertEqual(iie.iie_continuo(0.0, 20.0)["iie"], 0.0)

    def test_monotonia_respecto_de_la_lluvia(self):
        a = iie.iie_continuo(2.0, 50.0)["iie"]
        b = iie.iie_continuo(6.0, 50.0)["iie"]
        c = iie.iie_continuo(11.0, 50.0)["iie"]
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_acotado_a_100(self):
        self.assertLessEqual(iie.iie_continuo(200.0, 100.0)["iie"], 100.0)

    def test_piso_por_alerta_smn(self):
        self.assertGreaterEqual(iie.iie_continuo(0.0, 20.0, "naranja")["iie"], 75.0)
        self.assertGreaterEqual(iie.iie_continuo(0.0, 20.0, "rojo")["iie"], 90.0)


class TestGeometria(unittest.TestCase):
    """Point-in-polygon: si esto falla, las alertas del SMN se aplican mal."""

    # Cuadrado que envuelve Añelo
    CUADRADO = [(-38.0, -69.0), (-38.0, -68.4), (-38.7, -68.4), (-38.7, -69.0)]

    def test_punto_interior(self):
        self.assertTrue(smn.punto_en_poligono(-38.353, -68.783, self.CUADRADO))

    def test_punto_exterior_al_norte(self):
        self.assertFalse(smn.punto_en_poligono(-30.0, -68.783, self.CUADRADO))

    def test_punto_exterior_al_este(self):
        self.assertFalse(smn.punto_en_poligono(-38.353, -60.0, self.CUADRADO))

    def test_poligono_degenerado(self):
        self.assertFalse(smn.punto_en_poligono(-38.35, -68.78, [(-38.0, -69.0)]))

    def test_los_tres_puntos_criticos_caen_en_el_cuadrado(self):
        for p in config.PUNTOS:
            self.assertTrue(
                smn.punto_en_poligono(p.lat, p.lon, self.CUADRADO),
                f"{p.nombre} quedó fuera",
            )


class TestPeorColor(unittest.TestCase):

    def _aviso(self, evento, color):
        return {"evento": evento, "color_smn": color, "poligonos": []}

    def test_toma_el_mas_severo(self):
        avisos = [self._aviso("Lluvia", "amarillo"), self._aviso("Tormenta", "naranja")]
        self.assertEqual(smn.peor_color(avisos), "naranja")

    def test_ignora_eventos_no_relevantes(self):
        # Un alerta por viento no debe cortar los caminos por anegamiento
        avisos = [self._aviso("Viento", "rojo")]
        self.assertIsNone(smn.peor_color(avisos))

    def test_sin_avisos(self):
        self.assertIsNone(smn.peor_color([]))


class TestConsolidado(unittest.TestCase):

    def test_toma_el_peor_punto(self):
        regs = [{"nivel": "verde"}, {"nivel": "rojo"}, {"nivel": "amarillo"}]
        self.assertEqual(iie.nivel_consolidado(regs), "rojo")

    def test_lista_vacia(self):
        self.assertEqual(iie.nivel_consolidado([]), "verde")


if __name__ == "__main__":
    unittest.main(verbosity=2)
