"""Scene Intelligence — environment + lighting per scene."""
class SceneIntelligence:
    LIGHT = {"DAY":"natural soft","DUSK":"golden rim","NIGHT":"moody low-key","DAWN":"cool blue-gold"}
    def build(self, scene, direction):
        return {"scene_id":scene.id,"location":scene.location,"time_of_day":scene.time_of_day,
                "palette":direction["palette"],"lighting":self.LIGHT.get(scene.time_of_day,"balanced"),
                "env_prompt":f'{scene.location}, {scene.time_of_day.lower()}, {direction["palette"]}, {direction["tone"]}'}
