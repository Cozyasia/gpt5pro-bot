import unittest
from neyrobot_prod.marketplace_studio import ProductProject, Output, Marketplace, Stage, select_output, select_marketplace, add_references, continue_after_references, set_brief

class TranscriptTests(unittest.TestCase):
    def test_transcribed_brief_matches_text_brief(self):
        project = select_marketplace(select_output(ProductProject(), Output.COMPLETE), Marketplace.OZON)
        project = continue_after_references(add_references(project, ('photo-id',)))
        text = 'Фарфоровый сервиз на шесть персон'
        self.assertEqual(set_brief(project, text).brief, text)
        self.assertEqual(set_brief(project, text).stage, Stage.REVIEW)

if __name__ == '__main__':
    unittest.main()
