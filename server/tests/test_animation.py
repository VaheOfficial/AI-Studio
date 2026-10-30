"""Composition, dispatch and narration integration checks without model inference."""
import copy
import json
import math,wave,array
import unittest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
import test_agents as foundation
from studio.agent import tools
from studio.agent.types import ToolContext, ToolOutcome, ToolFailure
from studio.agents import animation_tools
from studio.animation import catalog, recipes, render
from studio.schemas import Output
from studio.schemas_animation import AnimationComposition
from studio.schemas_animation import AnimationRenderRequest
from studio import config,media
from studio.events import bus
from studio.jobs import jobs
from studio.workspace import state
from studio.agents.coverage import browser_installed


class CompositionTests(unittest.TestCase):
    def test_mosaic_scene_rejects_unbounded_and_ambiguous_controls(self):
        value=recipes.recipe('contour-aquarium').model_dump(mode='json')
        for props in ({'palette':{'unknown':'#ffffff'}},{'palette':{'fishBody':'red'}},{'fish_scale':20},{'path':[{'t':1,'x':600,'y':400},{'t':1,'x':610,'y':400}]},{'body_profile':[[.1,2,-2],[1,3,-3]]},{'motion':{'amp':[[2,1],[1,1]]}},{'code':'alert(1)'}):
            bad=copy.deepcopy(value);bad['scenes'][0]['layers'][0]['props']=props
            with self.subTest(props=props),self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)
        repeated=copy.deepcopy(value);second=copy.deepcopy(repeated['scenes'][0]);second['id']='second';repeated['scenes'].append(second)
        with self.assertRaisesRegex(ValidationError,'unique across'):AnimationComposition.model_validate(repeated)

    def test_mosaic_scripts_only_embedded_when_requested(self):
        value=recipes.recipe('contour-aquarium').model_dump(mode='json')
        bad=copy.deepcopy(value)
        bad['scenes'][0]['layers'][0]['props_tracks']={'fish_scale':[{'time':0,'value':1},{'time':1,'value':1.2}]}
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)
        html=render.page_html(value)
        self.assertIn('window.createMosaicScene',html)
        self.assertIn('function buildSpine',html)
        self.assertNotIn('window.camOverride',html)
        plain=recipes.recipe('kinetic').model_dump(mode='json')
        self.assertNotIn('function buildSpine',render.page_html(plain))

    def test_painterly_controls_and_light_pass_are_bounded(self):
        value=recipes.recipe('painted-lake').model_dump(mode='json')
        for change in ({'smear':[float('nan'),0]},{'smear':[121,0]},{'boil':25},{'stroke_scale':0},{'bloom':4}):
            bad=copy.deepcopy(value);bad['scenes'][0]['painterly'].update(change)
            with self.subTest(change=change),self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)
        value['scenes'][0]['painterly']=None
        with self.assertRaisesRegex(ValidationError,'Light paint passes require'):AnimationComposition.model_validate(value)
    def test_surface_fibers_reject_unsupported_geometry_and_excess_budgets(self):
        sphere={'id':'fur','kind':'sphere','fibers':{'count':8000,'length':.02}}
        catalog.validate_props('scene3d',{'nodes':[sphere]})
        for change in ({'kind':'box'},{'fibers':{'count':8001,'length':.02}},{'fibers':{'count':100,'length':.09}}):
            with self.subTest(change=change),self.assertRaises(ValueError):catalog.validate_props('scene3d',{'nodes':[sphere|change]})
        with self.assertRaisesRegex(ValueError,'16000 surface fibers'):catalog.validate_props('scene3d',{'nodes':[sphere|{'id':f'fur-{i}'} for i in range(3)]})
        scenes=[{'id':f'scene-{i}','duration':1,'layers':[{'id':'world','component':'scene3d','props':{'nodes':[sphere|{'id':'one'},sphere|{'id':'two'}]}}]} for i in range(5)]
        with self.assertRaisesRegex(ValidationError,'64000 surface fibers'):AnimationComposition.model_validate({'title':'Fiber budget','scenes':scenes})
    def test_pigment_timing_pressure_and_texture_budgets_are_checked(self):
        value={'title':'Brush bounds','scenes':[{'id':'scene','duration':2,'layers':[{'id':'paint','component':'brush','props':{'strokes':[{'points':[[.1,.3,.2],[.8,.7,1]],'width':.02,'color':'#28352c','start':.5,'duration':1}]}}]}]}
        AnimationComposition.model_validate(value)
        for change in ('pressure','timing','count'):
            bad=copy.deepcopy(value);strokes=bad['scenes'][0]['layers'][0]['props']['strokes']
            if change=='pressure':strokes[0]['points'][0][2]=-1
            elif change=='timing':strokes[0]['duration']=2
            else:bad['scenes'][0]['layers'][0]['props']['strokes']=strokes*257
            with self.subTest(change=change),self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)
        textured={'title':'Texture bounds','scenes':[{'id':'scene','duration':2,'layers':[{'id':'objects','component':'scene3d','props':{'nodes':[{'id':f'ball-{i}','kind':'sphere','texture':'wool','texture_scale':1+i/10} for i in range(33)]}}]}]}
        with self.assertRaisesRegex(ValidationError,'32 procedural texture variants'):AnimationComposition.model_validate(textured)
        textured['scenes'][0]['layers'][0]['props']['nodes'].pop()
        AnimationComposition.model_validate(textured)
    def base(self):
        return {'title':'Test film','scenes':[{'id':'scene','duration':2,'layers':[{'id':'title','component':'text','props':{'text':'Hello'}}]}]}

    def test_every_recipe_is_valid_and_distinct(self):
        values=[recipes.recipe(key) for key in recipes.RECIPES]
        self.assertGreaterEqual(len(values),20)
        structures=[json.dumps(v.model_dump()['scenes'],sort_keys=True) for v in values]
        self.assertEqual(len(set(structures)),len(values))
        used={layer.component for v in values for scene in v.scenes for layer in scene.layers}
        self.assertEqual(used,set(catalog.COMPONENTS)-{'image'})

    def test_invalid_geometry_timing_and_parameters_are_rejected(self):
        edits=[{'width':257},{'width':1920,'height':1920},{'fps':120},{'version':2},
               {'palette':{'ink':'url(http://example.com)'}},{'script':'alert(1)'}]
        for edit in edits:
            with self.subTest(edit=edit),self.assertRaises(ValidationError):AnimationComposition.model_validate(self.base()|edit)
        for edit in [{'start':3},{'duration':3},{'opacity':math.nan},{'component':'javascript'},
                     {'props':{'text':'Hi','script':'alert(1)'}},
                     {'tracks':{'opacity':[{'time':0,'value':2}]}},
                     {'tracks':{'x':[{'time':1,'value':0},{'time':0,'value':1}]}},
                     {'tracks':{'x':[{'time':0,'value':0},{'time':0,'value':1}]}},
                     {'tracks':{'x':[{'time':3,'value':0}]}},
                     {'tracks':{'url':[{'time':0,'value':0}]}},
                     {'props':{'text':'Hi','size':math.inf}}]:
            value=self.base();value['scenes'][0]['layers'][0].update(edit)
            with self.subTest(edit=edit),self.assertRaises(ValidationError):AnimationComposition.model_validate(value)

    def test_scene_graph_rejects_cycles_invalid_joints_and_outside_timing(self):
        good={'title':'Joint study','scenes':[{'id':'scene','duration':2,'layers':[{'id':'world','component':'scene3d','props':{'nodes':[{'id':'joint','kind':'group'},{'id':'limb','kind':'capsule','parent':'joint','tracks':{'rz':[{'time':0,'value':0},{'time':2,'value':90}]}}]}}]}]}
        AnimationComposition.model_validate(good)
        for edit in [{'parent':'limb'},{'parent':'missing'},{'id':'limb'},{'tracks':{'sy':[{'time':0,'value':0}]}},{'tracks':{'x':[{'time':3,'value':1}]}},{'tracks':{'x':[{'time':0,'value':0},{'time':0,'value':1}]}},{'kind':'model'},{'source':'https://example.com/model.glb'},{'kind':'polygon','points':[[0,0],[1,0]]}]:
            bad=copy.deepcopy(good);bad['scenes'][0]['layers'][0]['props']['nodes'][0].update(edit)
            with self.subTest(edit=edit),self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)

    def test_presets_and_continuous_tracks_have_explicit_bounds(self):
        from studio.animation.rigs import expand_presets
        value={'id':'hero','kind':'preset','preset':'mascot','action':'wave'}
        catalog.validate_props('scene3d',{'nodes':[value]})
        expanded=expand_presets([value]);self.assertGreater(len(expanded),20)
        arm=next(n for n in expanded if n['id']=='hero-right-arm-pivot');self.assertEqual(arm['motion']['axis'],'rz')
        for nodes in [[value|{'action':'flight'}],[value|{'preset':'missing'}],[value,{'id':'hero-face','kind':'sphere'}],[value|{'motion':{'axis':'x','kind':'sway','amount':300}}]]:
            with self.assertRaises(ValueError):catalog.validate_props('scene3d',{'nodes':nodes})
        bad=self.base();bad['scenes'][0]['layers'][0]['tracks']={'scale':[{'time':0,'value':0},{'time':2,'value':1,'interpolation':'monotone_log'}]}
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)
        good=self.base();good['scenes'][0]['camera']={'tracks':{'zoom':[{'time':0,'value':1},{'time':2,'value':2,'interpolation':'monotone_log'}]}}
        AnimationComposition.model_validate(good)
        for node in [{'id':'part','kind':'sphere','repeat':{'count':2,'layout':'radial'}},{'id':'part','kind':'polygon','points':[[0,0],[1,1],[2,2]]},{'id':'part','kind':'tube','curve':[[0,0,0],[0,0,0]]},{'id':'part','kind':'lathe','profile':[[0,0],[0,1]]},{'id':'part','kind':'box','tracks':{'roughness':[{'time':0,'value':2}]}}]:
            with self.assertRaises(ValueError):catalog.validate_props('scene3d',{'nodes':[node]})
        with self.assertRaises(ValueError):catalog.validate_props('scene3d',{'nodes':[{'id':'part'+str(i),'kind':'box','repeat':{'count':1024,'layout':'radial'}} for i in range(5)]})
        with self.assertRaises(ValueError):catalog.validate_props('text',{'text':'ابقَ فضوليًا','mode':'letters'})

    def test_fluid_timing_and_targeted_review_are_bounded(self):
        good={'title':'Ink','scenes':[{'id':'scene','duration':2,'layers':[{'id':'ink','component':'fluid','props':{'emitters':[{'x':.5,'y':.5,'color':'#234567','end':1}]}}]}]}
        value=AnimationComposition.model_validate(good)
        AnimationRenderRequest(composition=value,review_times=[.01,1.8],review_crop={'x':.1,'y':.1,'width':.2,'height':.2})
        for request in [{'review_times':[2]},{'review_times':[math.nan]},{'review_times':[1]*25},{'review_crop':{'x':.9,'y':0,'width':.2,'height':.1}}]:
            with self.assertRaises(ValidationError):AnimationRenderRequest(composition=value,**request)
        for duration,end in [(31,1),(2,3),(2,0)]:
            bad=copy.deepcopy(good);bad['scenes'][0]['duration']=duration;bad['scenes'][0]['layers'][0]['props']['emitters'][0]['end']=end
            with self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)

    def test_glb_rejects_external_buffers_and_truncated_storage(self):
        import struct,tempfile
        from studio.animation.glb import inspect_glb
        from studio.jobs import JobError
        def pack(document):
            body=json.dumps(document).encode();body+=b' '*((-len(body))%4)
            return struct.pack('<III',0x46546c67,2,20+len(body))+struct.pack('<II',len(body),0x4e4f534a)+body
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.glb';path.write_bytes(pack({'asset':{'version':'2.0'}}));inspect_glb(path)
            for data in [pack({'buffers':[{'uri':'https://example.com/a.bin'}]}),pack({'images':[{'uri':'data:image/png;base64,a'}]}),pack({'extensionsUsed':['KHR_draco_mesh_compression']}),pack({'bufferViews':[{'byteLength':32}]}),pack({'accessors':[{'count':2000001}]}),b'not glb',pack({})[:-1]]:
                path.write_bytes(data)
                with self.assertRaises(JobError):inspect_glb(path)

    def test_duplicate_ids_and_outside_cues_are_rejected(self):
        value=self.base();value['scenes'].append(copy.deepcopy(value['scenes'][0]))
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(value)
        value=self.base();value['scenes'][0]['layers']*=2
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(value)
        for edit in [{'captions':[{'start':1,'end':3,'text':'Late'}]},
                     {'captions':[{'start':1,'end':.5,'text':'Reverse'}]},
                     {'captions':[{'start':0,'end':1.5,'text':'One'},{'start':1,'end':2,'text':'Two'}]},
                     {'audio':[{'id':'voice','start':2}]},
                     {'sound':{'cues':[{'time':2,'type':'click'}]}}]:
            with self.subTest(edit=edit),self.assertRaises(ValidationError):AnimationComposition.model_validate(self.base()|edit)

    def test_diagram_references_and_expensive_weather_are_checked(self):
        for kind,props in [('diagram',{'nodes':[{'id':'a','label':'A','x':0,'y':0}],'edges':[['a','missing']]}),
                           ('chart',{'values':[1,2],'labels':['One']}),
                           ('weather',{'kind':'mist','count':41})]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):catalog.validate_props(kind,props)
        with self.assertRaises(ValueError):catalog.validate_props('shape',{'kind':'ring','to':'circle'})

    def test_narration_is_never_implicitly_generated(self):
        value=AnimationComposition.model_validate(self.base()|{'audio':[{'id':'voice','text':'Hello'}]})
        result=render.validation(value)
        self.assertEqual(len(result.warnings),1)
        self.assertIn('will not invoke',result.warnings[0])

    def test_script_like_copy_is_rendered_as_data(self):
        value=self.base();value['title']='</script><script>alert(1)</script>'
        source=render.page_html(AnimationComposition.model_validate(value).model_dump())
        self.assertNotIn('</script><script>alert(1)',source)
        self.assertIn('\\u003c/script>',source)

    def test_parent_graph_masks_and_component_tracks_are_validated(self):
        base={'title':'Controlled assembly','scenes':[{'id':'scene','duration':2,'layers':[
            {'id':'assembly','component':'group','mask':{'kind':'ellipse'},'tracks':{'mask_reveal':[{'time':0,'value':0},{'time':1,'value':1}]}},
            {'id':'surface','component':'mesh','parent':'assembly','props':{'kind':'torus'},'props_tracks':{'roughness':[{'time':0,'value':.7},{'time':2,'value':.1}]},'color_tracks':{'color':[{'time':0,'value':'$accent'},{'time':2,'value':'#8065b4'}]}}]}]}
        AnimationComposition.model_validate(base)
        edits=[{'parent':'missing'},{'props_tracks':{'roughness':[{'time':0,'value':5}]}},
               {'props_tracks':{'segments':[{'time':0,'value':30}]}},
               {'color_tracks':{'kind':[{'time':0,'value':'#ffffff'}]}},
               {'color_tracks':{'color':[{'time':0,'value':'javascript:bad'}]}},
               {'paint':{'colors':['$accent','invalid']}}]
        for edit in edits:
            value=copy.deepcopy(base);value['scenes'][0]['layers'][1].update(edit)
            with self.subTest(edit=edit),self.assertRaises(ValidationError):AnimationComposition.model_validate(value)
        value=copy.deepcopy(base);value['scenes'][0]['layers'][0]['parent']='assembly'
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(value)

    def test_vector_path_command_groups_and_fonts_are_checked(self):
        catalog.validate_path('M0 0C10 0 20 10 30 30Q40 0 50 20Z')
        for path in ['M0','M0 0C0 1','M0 0L1e999 0','M0 0A-1 5 0 0 1 20 20','M0 0A5 5 0 3 1 20 20','M0 0e','L0 0']:
            with self.subTest(path=path),self.assertRaises(ValueError):catalog.validate_path(path)
        value=self.base();value['scenes'][0]['layers'][0]['props']['font']='not-attached'
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(value)
        value['fonts']=[{'id':'not-attached','source':'font.woff2'}];AnimationComposition.model_validate(value)
        value['fonts']*=2
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(value)


class AnimationDispatchTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(browser_installed() and media.find('ffmpeg'),'Requires browser and FFmpeg')
    async def test_painterly_light_pass_changes_image_and_restores_after_seek(self):
        import asyncio
        from PIL import Image,ImageStat
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        value=AnimationComposition.model_validate({'title':'Paint and light','width':256,'height':256,'fps':12,'scenes':[{'id':'paint','duration':2,'background':'#172645','painterly':{'boil':0,'grain':0,'flow':0},'layers':[{'id':'disc','component':'shape','width':.5,'height':.5,'props':{'kind':'circle','fill':'#aa6655'}},{'id':'light','component':'shape','paint_pass':'light','width':.4,'height':.4,'props':{'kind':'circle','fill':'#c08040'},'tracks':{'opacity':[{'time':0,'value':0},{'time':1,'value':1}]}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[0,1.2,0]));result=await jobs.wait(job.id)
        self.assertEqual(result.status,'done',result.error);folder=config.OUTPUTS_DIR/'animations'/job.id
        self.assertEqual((folder/'frame-01.png').read_bytes(),(folder/'frame-03.png').read_bytes())
        with Image.open(folder/'frame-01.png') as im:dark=sum(ImageStat.Stat(im.convert('RGB')).mean)
        with Image.open(folder/'frame-02.png') as im:lit=sum(ImageStat.Stat(im.convert('RGB')).mean)
        self.assertGreater(lit,dark+10)
    async def asyncSetUp(self):await foundation.AgentStateTests.asyncSetUp(self)
    async def asyncTearDown(self):await foundation.AgentStateTests.asyncTearDown(self)
    def ctx(self,invoke=None):return ToolContext('owner','animation-test',lambda _:None,vision=True,invoke=invoke)

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_tessera_assembly_reveals_and_restores_exact_artwork(self):
        import asyncio
        from PIL import Image
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        props={'view_box':[0,0,100,100],'paths':[{'d':'M50 5A45 45 0 1 1 49.9 5Z','fill':'#d79245'}],'texture':'mosaic','tile_flow':'radial','tile_size':.035,'tile_scatter':.7}
        value=AnimationComposition.model_validate({'title':'Assembling artwork','width':256,'height':256,'fps':12,'palette':{'background':'#102030'},'scenes':[{'id':'scene','duration':2,'layers':[{'id':'art','component':'vector','width':1,'height':1,'props':props,'props_tracks':{'tile_assembly':[{'time':0,'value':0},{'time':1,'value':1},{'time':2,'value':0}]}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[0,.4,1,1.7,1]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error);folder=config.OUTPUTS_DIR/'animations'/job.id
        counts=[]
        for index in (1,2,3):
            with Image.open(folder/f'frame-{index:02d}.png') as im:counts.append(sum(1 for pixel in im.convert('RGB').getdata() if pixel!=(16,32,48)))
        self.assertEqual(counts[0],0);self.assertGreater(counts[1],100);self.assertGreater(counts[2],counts[1]);self.assertEqual((folder/'frame-03.png').read_bytes(),(folder/'frame-05.png').read_bytes())
        bad=value.model_dump(mode='json');bad['scenes'][0]['layers'][0]['props_tracks']['tile_assembly'][1]['value']=1.1
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_mosaic_contours_and_mirrored_art_restore(self):
        import asyncio
        from PIL import Image,ImageChops,ImageStat,ImageOps
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        props={'view_box':[0,0,100,100],'paths':[{'d':'M10 90V40A30 30 0 0 1 70 40V90Z','fill':'#de8530','stroke':'#152522','width':2}],'texture':'mosaic','tile_flow':'arch','tile_origin':[.4,.4],'tile_grout':'#152522','tile_size':.05,'tile_relief':.6,'tile_variation':.2,'tile_outlines':True,'tile_reveal':'center'}
        value=AnimationComposition.model_validate({'title':'Mirrored tesserae','width':256,'height':256,'fps':12,'palette':{'background':'#102030'},'scenes':[{'id':'scene','duration':2.5,'layers':[{'id':'art','component':'vector','width':.8,'height':.8,'props':props,'tracks':{'scale_x':[{'time':0,'value':1},{'time':1,'value':-1},{'time':2,'value':1}]}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[0,1,2]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error);folder=config.OUTPUTS_DIR/'animations'/job.id
        self.assertEqual((folder/'frame-01.png').read_bytes(),(folder/'frame-03.png').read_bytes())
        with Image.open(folder/'frame-01.png') as first,Image.open(folder/'frame-02.png') as second:
            difference=ImageChops.difference(ImageOps.mirror(first.convert('RGB')),second.convert('RGB'))
            self.assertLess(max(ImageStat.Stat(difference).mean),2)
        bad=value.model_dump(mode='json');bad['scenes'][0]['layers'][0]['tracks']['scale_x'][1]['value']=-11
        with self.assertRaises(ValidationError):AnimationComposition.model_validate(bad)

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_surface_fibers_change_silhouette_and_repeat_after_seeking(self):
        import asyncio
        from PIL import Image,ImageChops
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        sphere={'id':'sphere','kind':'sphere','dimensions':[.5,1,1],'color':'#dcbd8d','fibers':{'count':3000,'length':.08,'thickness':.005},'tracks':{'ry':[{'time':0,'value':0},{'time':1,'value':60}]}}
        value=AnimationComposition.model_validate({'title':'Fiber silhouette','width':256,'height':256,'fps':12,'scenes':[{'id':'scene','duration':1,'background':'#000000','layers':[{'id':'world','component':'scene3d','width':1,'height':1,'props':{'nodes':[sphere],'camera':{'position':[0,0,3],'target':[0,0,0]},'ambient':1,'lights':[]}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[.1,.8,.1]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error);folder=config.OUTPUTS_DIR/'animations'/job.id
        self.assertEqual((folder/'frame-01.png').read_bytes(),(folder/'frame-03.png').read_bytes())
        plain=value.model_copy(deep=True);del plain.scenes[0].layers[0].props['nodes'][0]['fibers']
        baseline=render.submit(AnimationRenderRequest(composition=plain,session_id='owner',preview_only=True,review_times=[.1]));baseline_result=await jobs.wait(baseline.id);self.assertEqual(baseline_result.status,'done',baseline_result.error)
        with Image.open(folder/'frame-01.png') as image,Image.open(config.OUTPUTS_DIR/'animations'/baseline.id/'frame-01.png') as smooth:
            fibers=image.convert('RGB');surface=smooth.convert('RGB');self.assertIsNotNone(ImageChops.difference(fibers,surface).getbbox())
            silhouette=lambda im:sum(1 for px in im.getdata() if max(px)>30)
            self.assertGreater(silhouette(fibers),silhouette(surface)+100)

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_pressure_paint_deposits_progressively_and_seeks_exactly(self):
        import asyncio
        from PIL import Image
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        value=AnimationComposition.model_validate({'title':'Pressure paint','width':256,'height':256,'fps':12,'palette':{'background':'#ffffff'},'scenes':[{'id':'scene','duration':2,'layers':[{'id':'paint','component':'brush','width':1,'height':1,'props':{'strokes':[{'points':[[.15,.3,.1],[.5,.5,1.4],[.85,.7,.1]],'width':.15,'color':'#182e25','start':.3,'duration':1.2,'style':'ink'}]}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[.1,.8,1.8,.8]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error);folder=config.OUTPUTS_DIR/'animations'/job.id
        counts=[]
        for i in (1,2,3):
            with Image.open(folder/f'frame-{i:02d}.png') as image:counts.append(sum(1 for px in image.convert('RGB').getdata() if min(px)<200))
        self.assertEqual(counts[0],0);self.assertGreater(counts[1],200);self.assertGreater(counts[2],counts[1]);self.assertEqual((folder/'frame-02.png').read_bytes(),(folder/'frame-04.png').read_bytes())

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_tiled_art_preserves_curved_layout_and_transparent_boundaries(self):
        import asyncio
        from PIL import Image
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        props={'view_box':[0,0,100,100],'paths':[{'d':'M50 10A40 40 0 1 1 49.9 10Z','fill':'#ce843a'}],'texture':'mosaic','tile_flow':'radial','tile_size':.05}
        value=AnimationComposition.model_validate({'title':'Tiled circle','width':256,'height':256,'fps':12,'style':'mosaic','palette':{'background':'#102030'},'finishing':{'grain':0,'vignette':0},'scenes':[{'id':'scene','duration':1,'layers':[{'id':'art','component':'vector','width':1,'height':1,'props':props}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[.2,.8,.2]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error);folder=config.OUTPUTS_DIR/'animations'/job.id
        background=value.model_copy(deep=True);background.scenes[0].layers[0].opacity=0
        baseline=render.submit(AnimationRenderRequest(composition=background,session_id='owner',preview_only=True,review_times=[.2]));baseline_result=await jobs.wait(baseline.id);self.assertEqual(baseline_result.status,'done',baseline_result.error)
        with Image.open(config.OUTPUTS_DIR/'animations'/baseline.id/'frame-01.png') as image:corner=image.convert('RGB').crop((0,0,16,16)).tobytes()
        with Image.open(folder/'frame-01.png') as image:
            pixels=image.convert('RGB');self.assertEqual(pixels.crop((0,0,16,16)).tobytes(),corner);self.assertGreater(len(set(pixels.crop((30,30,226,226)).getdata())),200)
        self.assertEqual((folder/'frame-01.png').read_bytes(),(folder/'frame-03.png').read_bytes())

    async def test_discover_recipe_edit_validate_through_dispatcher(self):
        ctx=self.ctx()
        found=await tools.execute('animation_catalog',{},ctx);self.assertTrue(found.ok,found.output)
        self.assertEqual(set(json.loads(found.output)['components']),set(catalog.COMPONENTS))
        focused=await tools.execute('animation_catalog',{'component':'mesh'},ctx)
        self.assertTrue(focused.ok);self.assertEqual(json.loads(focused.output)['component'],'mesh');self.assertLess(len(focused.output),len(found.output))
        result=await tools.execute('animation_recipe',{'recipe':'punk-zine','title':'New rhythm'},ctx)
        self.assertTrue(result.ok,result.output);film=json.loads(result.output)
        film['scenes'][0]['layers'][1]['props']['text']='MAKE YOUR OWN RHYTHM'
        result=await tools.execute('animation_validate',{'composition':film},ctx)
        self.assertTrue(result.ok,result.output);self.assertEqual(json.loads(result.output)['frames'],360)
        invalid=await tools.execute('animation_recipe',{'recipe':'missing'},ctx)
        self.assertFalse(invalid.ok)

    async def test_project_revisions_are_atomic_scoped_and_compact(self):
        result=await tools.execute('animation_project',{'action':'create','recipe':'contour','title':'A directed film'},self.ctx());self.assertTrue(result.ok,result.output)
        first=json.loads(result.output);self.assertNotIn('composition',first)
        changed=await tools.execute('animation_project',{'action':'edit','project_id':first['project_id'],'version':first['version'],'edits':[{'op':'set','scene_id':'first-form','layer_id':'hero','path':'/props/roughness','value':.12},{'op':'set','path':'/palette/accent','value':'#5577bb'}]},self.ctx())
        self.assertTrue(changed.ok,changed.output);second=json.loads(changed.output);self.assertEqual(second['version'],2)
        stale=await tools.execute('animation_project',{'action':'edit','project_id':first['project_id'],'version':1,'edits':[{'op':'set','path':'/title','value':'Stale'}]},self.ctx());self.assertFalse(stale.ok)
        denied=await tools.execute('animation_project',{'action':'read','project_id':first['project_id']},ToolContext('other','cross-chat',lambda _:None));self.assertFalse(denied.ok)
        invalid=await tools.execute('animation_project',{'action':'edit','project_id':first['project_id'],'version':2,'edits':[{'op':'set','path':'/title','value':'Should not commit'},{'op':'set','scene_id':'first-form','layer_id':'hero','path':'/props/roughness','value':-1}]},self.ctx());self.assertFalse(invalid.ok)
        read=await tools.execute('animation_project',{'action':'read','project_id':first['project_id'],'scene_id':'first-form','include_composition':True},self.ctx())
        value=json.loads(read.output);self.assertEqual(value['version'],2);self.assertEqual(value['title'],'A directed film');self.assertEqual(value['scene']['layers'][-1]['props']['roughness'],.12)
        rejected=await tools.execute('animation_render',{'project_id':first['project_id'],'version':1},self.ctx());self.assertFalse(rejected.ok)

    async def test_named_node_edits_are_atomic_and_remove_whole_branches(self):
        film={'title':'Named joints','scenes':[{'id':'scene','duration':2,'layers':[{'id':'world','component':'scene3d','props':{'nodes':[{'id':'joint','kind':'group'},{'id':'limb','kind':'box','parent':'joint'},{'id':'floor','kind':'plane'}]}}]}]}
        result=await tools.execute('animation_project',{'action':'create','composition':film},self.ctx());first=json.loads(result.output)
        changed=await tools.execute('animation_project',{'action':'edit','project_id':first['project_id'],'version':1,'edits':[{'op':'set','scene_id':'scene','layer_id':'world','node_id':'limb','path':'/roughness','value':.2}]},self.ctx());self.assertTrue(changed.ok,changed.output)
        read=await tools.execute('animation_project',{'action':'read','project_id':first['project_id'],'scene_id':'scene','layer_id':'world','node_id':'limb'},self.ctx());value=json.loads(read.output);self.assertEqual(value['node']['roughness'],.2);self.assertNotIn('scene',value)
        denied=await tools.execute('animation_project',{'action':'edit','project_id':first['project_id'],'version':2,'edits':[{'op':'set','scene_id':'scene','layer_id':'world','node_id':'missing','path':'/color','value':'#000000'}]},self.ctx());self.assertFalse(denied.ok)
        changed=await tools.execute('animation_project',{'action':'edit','project_id':first['project_id'],'version':2,'edits':[{'op':'add_node','scene_id':'scene','layer_id':'world','value':{'id':'detail','kind':'sphere','parent':'limb'}},{'op':'remove_node','scene_id':'scene','layer_id':'world','node_id':'joint'}]},self.ctx());self.assertTrue(changed.ok,changed.output)
        read=await tools.execute('animation_project',{'action':'read','project_id':first['project_id'],'scene_id':'scene','layer_id':'world'},self.ctx());self.assertEqual([node['id'] for node in json.loads(read.output)['layer']['props']['nodes']],['floor'])

    async def test_voice_uses_existing_dispatcher_and_measured_duration(self):
        calls=[]
        output=Output(id='fixture',kind='audio',url='/files/outputs/fixture.wav',model_id='fixture',prompt='Hello',params={},created_at='2026-10-12T00:00:00Z')
        async def invoke(name,args):calls.append((name,args));return ToolOutcome(True,'prepared',artifacts=[output])
        film=recipes.recipe('kinetic').model_dump();film['audio']=[{'id':'voice','text':'Hello','start':1,'voice_id':'expressive'}]
        with patch.object(render,'asset_path',return_value=Path('fixture.wav')),patch.object(render,'probe_audio',return_value=1.75):
            result=await tools.execute('animation_prepare_voice',{'composition':film},self.ctx(invoke))
        self.assertTrue(result.ok,result.output);value=json.loads(result.output)
        self.assertEqual(calls,[('text_to_speech',{'text':'Hello','voice_id':'expressive'})])
        self.assertEqual(value['timings'][0]['end'],2.75)
        self.assertEqual(value['composition']['audio'][0]['source'],output.url)

    async def test_attached_voice_is_reused_and_failure_is_propagated(self):
        async def fail(*args):return ToolOutcome(False,'Speech unavailable')
        film=recipes.recipe('kinetic').model_dump();film['audio']=[{'id':'voice','text':'Hello','source':'already.wav'}]
        result=await tools.execute('animation_prepare_voice',{'composition':film},self.ctx(fail))
        self.assertTrue(result.ok);self.assertEqual(json.loads(result.output)['timings'],[])
        film['audio'][0].pop('source')
        result=await tools.execute('animation_prepare_voice',{'composition':film},self.ctx(fail))
        self.assertFalse(result.ok);self.assertEqual(result.output,'Speech unavailable')

    async def test_voice_overrun_is_reported_and_missing_dispatcher_fails(self):
        output=Output(id='fixture',kind='audio',url='/files/outputs/fixture.wav',model_id='fixture',prompt='',params={},created_at='2026-10-12T00:00:00Z')
        async def invoke(*args):return ToolOutcome(True,'prepared',artifacts=[output])
        film=recipes.recipe('kinetic').model_dump();film['audio']=[{'id':'voice','text':'Hello','start':14}]
        with patch.object(render,'asset_path',return_value=Path('fixture.wav')),patch.object(render,'probe_audio',return_value=3):
            result=await tools.execute('animation_prepare_voice',{'composition':film},self.ctx(invoke))
        self.assertEqual(json.loads(result.output)['overruns'],[{'id':'voice','required_end':17}])
        result=await tools.execute('animation_prepare_voice',{'composition':film},self.ctx())
        self.assertFalse(result.ok)

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_real_local_image_and_timed_audio_export(self):
        from PIL import Image
        bus.bind_loop(__import__('asyncio').get_running_loop());state.set_root('owner',str(self.root))
        config.OUTPUTS_DIR.mkdir(parents=True,exist_ok=True)
        asset=self.root/'art.png';Image.new('RGB',(80,80),'#ef804e').save(asset)
        audio=self.root/'tone.wav'
        with wave.open(str(audio),'wb') as stream:
            stream.setparams((1,2,24000,0,'NONE','not compressed'))
            stream.writeframes(array.array('h',[int(math.sin(i/24000*math.tau*440)*7000) for i in range(6000)]).tobytes())
        value=AnimationComposition.model_validate({'title':'Local asset regression','width':256,'height':256,'fps':12,
            'scenes':[{'id':'scene','duration':2,'layers':[{'id':'asset','component':'image','props':{'source':str(asset)}}]}],
            'captions':[{'start':0,'end':2,'text':'A caption wraps inside this square frame.'}],
            'audio':[{'id':'tone','source':str(audio),'start':.5}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner'));result=await jobs.wait(job.id)
        self.assertEqual(result.status,'done',result.error)
        directory=config.OUTPUTS_DIR/'animations'/job.id
        report=json.loads((directory/'report.json').read_text())
        self.assertEqual(report['encoded_frames'],24);self.assertTrue(report['deterministic']);self.assertTrue(report['audio_present'])
        self.assertEqual(report['audio_tracks'][0]['start'],.5)
        with wave.open(str(directory/'soundtrack.wav'),'rb') as stream:
            samples=array.array('h',stream.readframes(stream.getnframes()));rate=stream.getframerate()
        self.assertEqual(max(abs(v) for v in samples[:int(.45*rate)]),0)
        self.assertGreater(max(abs(v) for v in samples[int(.5*rate):int(.7*rate)]),100)

    async def test_transparent_assets_are_preserved_and_reused(self):
        from PIL import Image
        state.set_root('owner',str(self.root));asset=self.root/'cutout.png'
        Image.new('RGBA',(40,40),(100,120,140,80)).save(asset)
        value=AnimationComposition.model_validate({'title':'Cutout','scenes':[{'id':'scene','duration':2,'layers':[{'id':name,'component':'image','props':{'source':str(asset)}} for name in ['one','two']]}]})
        directory=self.root/'render';directory.mkdir();data,_=render.prepare_assets(value,directory,'owner')
        sources=[layer['props']['source'] for layer in data['scenes'][0]['layers']]
        self.assertEqual(sources[0],sources[1])
        with Image.open(directory/sources[0]) as image:self.assertEqual(image.mode,'RGBA');self.assertEqual(image.getpixel((0,0))[3],80)

    async def test_phone_photo_orientation_and_reused_sprite_grid_preflight(self):
        from PIL import Image
        from studio.jobs import JobError
        state.set_root('owner',str(self.root));asset=self.root/'phone.jpg'
        photo=Image.new('RGB',(40,24),'red');photo.paste('blue',(20,0,40,24));exif=Image.Exif();exif[274]=6;photo.save(asset,exif=exif)
        value=AnimationComposition.model_validate({'title':'Phone photo','scenes':[{'id':'scene','duration':2,'layers':[{'id':'photo','component':'image','props':{'source':str(asset)}}]}]})
        directory=self.root/'oriented';directory.mkdir();data,_=render.prepare_assets(value,directory,'owner')
        with Image.open(directory/data['scenes'][0]['layers'][0]['props']['source']) as oriented:
            self.assertEqual(oriented.size,(24,40));self.assertGreater(oriented.getpixel((12,5))[0],200);self.assertGreater(oriented.getpixel((12,35))[2],200)
        value.scenes[0].layers.append(value.scenes[0].layers[0].model_copy(update={'id':'sprite','props':{'source':str(asset),'frames':5,'columns':5}}))
        directory=self.root/'invalid-sprite';directory.mkdir()
        with self.assertRaisesRegex(JobError,'divide evenly'):render.prepare_assets(value,directory,'owner')

    async def test_audio_must_fit_actual_fractional_encoded_end(self):
        from studio.jobs import JobError
        state.set_root('owner',str(self.root));asset=self.root/'short.wav'
        with wave.open(str(asset),'wb') as stream:
            stream.setparams((1,2,24000,0,'NONE','not compressed'));stream.writeframes(array.array('h',[0]*4800).tobytes())
        value=AnimationComposition.model_validate({'title':'Fractional end','width':256,'height':256,'fps':12,'scenes':[{'id':'scene','duration':1.01,'layers':[{'id':'text','component':'text','props':{'text':'End'}}]}],'audio':[{'id':'voice','source':str(asset),'start':.9}]})
        directory=self.root/'overrun';directory.mkdir()
        # 13 frames end at 1.0833 seconds; this audio ends at 1.1.
        with self.assertRaisesRegex(JobError,'beyond the encoded film'):render.prepare_assets(value,directory,'owner')

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_cancel_during_encoding_releases_renderer_for_next_job(self):
        import asyncio
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root))
        value=recipes.recipe('kinetic',width=256,height=256,fps=12)
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner'))
        for _ in range(300):
            current=jobs.get(job.id)
            if current.message and current.message.startswith('Frame '):break
            if current.status in ('done','error','cancelled'):self.fail(f'Job ended before cancellation: {current.status} {current.error}')
            await asyncio.sleep(.1)
        else:self.fail('Encoder did not start within 30 seconds')
        jobs.cancel(job.id);result=await asyncio.wait_for(jobs.wait(job.id),20)
        self.assertEqual(result.status,'cancelled');self.assertTrue((config.OUTPUTS_DIR/'animations'/job.id/'FAILED').exists())
        # A subsequent real browser export proves the serialization lock was released.
        value.scenes=value.scenes[:1];value.scenes[0].duration=1
        value.scenes[0].layers=[];value.sound.cues=[]
        retry=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True))
        result=await asyncio.wait_for(jobs.wait(retry.id),20);self.assertEqual(result.status,'done',result.error)

    @unittest.skipUnless(media.find('ffmpeg') and media.find('ffprobe'),'Requires FFmpeg')
    async def test_audio_analysis_measures_hits_and_silence_without_inference(self):
        state.set_root('owner',str(self.root));path=self.root/'hits.wav';rate=22050;values=array.array('h')
        for i in range(rate*3):
            t=i/rate;u=min(abs(t-hit) for hit in (.5,1,1.5,2));values.append(int(math.sin(math.tau*440*t)*16000*max(0,1-u/.06)))
        with wave.open(str(path),'wb') as stream:stream.setparams((1,2,rate,0,'NONE','not compressed'));stream.writeframes(values.tobytes())
        result=await tools.execute('animation_analyze_audio',{'source':str(path)},self.ctx());self.assertTrue(result.ok,result.output);self.assertEqual(result.display.kind,'audio_timing');value=json.loads(result.output)
        self.assertAlmostEqual(value['duration'],3,places=2);self.assertFalse(value['speech_transcribed']);self.assertGreater(len(value['pauses']),2)
        for expected in (.5,1,1.5,2):self.assertTrue(any(abs(hit['time']-expected)<.08 for hit in value['hits']))
        with wave.open(str(path),'wb') as stream:stream.setparams((1,2,rate,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*rate)
        result=await tools.execute('animation_analyze_audio',{'source':str(path)},self.ctx());value=json.loads(result.output);self.assertEqual(value['hits'],[]);self.assertIsNone(value['tempo_estimate_bpm']);self.assertEqual(value['tempo_confidence'],0)

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_real_fluid_tiles_review_crops_and_continuous_interpolation(self):
        import asyncio
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root));config.OUTPUTS_DIR.mkdir(parents=True,exist_ok=True)
        value=AnimationComposition.model_validate({'title':'Ink and tiles','width':256,'height':256,'fps':12,'scenes':[{'id':'ink','duration':2,'layers':[{'id':'flow','component':'fluid','props':{'resolution':'low','emitters':[{'x':.4,'y':.6,'color':'#234567','end':1.7}]}},{'id':'tiles','component':'tiles','opacity':.4,'props':{'columns':12,'rows':12,'formation':'moon','material':'gold','light_phase':0},'tracks':{'phase':[{'time':0,'value':0},{'time':.8,'value':1,'interpolation':'monotone'},{'time':2,'value':0,'interpolation':'monotone'}]}}]}]})
        request=AnimationRenderRequest(composition=value,session_id='owner',quality='final',review_times=[.4,.9,1.5],review_crop={'x':.2,'y':.2,'width':.5,'height':.5})
        job=render.submit(request);result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error)
        directory=config.OUTPUTS_DIR/'animations'/job.id;report=json.loads((directory/'report.json').read_text());self.assertEqual(report['encoded_frames'],24);self.assertTrue(report['deterministic']);self.assertEqual(report['review_times'],[.4,.9,1.5]);self.assertTrue((directory/'review-crops.jpg').is_file())
        from PIL import Image
        with Image.open(directory/'crop-01.png') as image:self.assertEqual(image.size,(128,128))

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_rendered_light_and_material_tracks_reset_after_backward_seek(self):
        import asyncio
        from PIL import Image
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root));config.OUTPUTS_DIR.mkdir(parents=True,exist_ok=True)
        value=AnimationComposition.model_validate({'title':'Light and material','width':256,'height':256,'fps':12,'scenes':[{'id':'scene','background':'#000000','duration':2,'layers':[{'id':'world','component':'scene3d','width':1,'height':1,'props':{'nodes':[{'id':'box','kind':'box','dimensions':[1.5,1.5,1.5],'color':'#ff0000','roughness':.7,'color_tracks':{'color':[{'time':0,'value':'#ff0000'},{'time':2,'value':'#3059eb'}]}}],'camera':{'position':[0,0,4],'target':[0,0,0]},'ambient':0,'environment':False,'lights':[]},'props_tracks':{'ambient':[{'time':0,'value':0},{'time':2,'value':2}]}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[.1,1.8,.1]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error)
        directory=config.OUTPUTS_DIR/'animations'/job.id
        self.assertEqual((directory/'frame-01.png').read_bytes(),(directory/'frame-03.png').read_bytes())
        with Image.open(directory/'frame-01.png') as image:early=image.getpixel((128,128))[:3]
        with Image.open(directory/'frame-02.png') as image:late=image.getpixel((128,128))[:3]
        self.assertGreater(sum(late),sum(early)*3);self.assertGreater(late[2],late[0])

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_sprite_sheet_frames_and_pixel_grid_are_time_driven(self):
        import asyncio
        from PIL import Image
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root));config.OUTPUTS_DIR.mkdir(parents=True,exist_ok=True)
        asset=self.root/'sprite.png';image=Image.new('RGBA',(32,16),(255,0,0,255));image.paste((0,0,255,255),(16,0,32,16));image.save(asset)
        value=AnimationComposition.model_validate({'title':'Sprite frames','width':256,'height':256,'fps':12,'scenes':[{'id':'scene','duration':1,'pixel_size':8,'layers':[{'id':'sprite','component':'image','width':1,'height':1,'props':{'source':str(asset),'frames':2,'columns':2,'frame_rate':2,'pixelated':True}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',preview_only=True,review_times=[.2,.7,.2]));result=await jobs.wait(job.id);self.assertEqual(result.status,'done',result.error)
        directory=config.OUTPUTS_DIR/'animations'/job.id
        with Image.open(directory/'frame-01.png') as image:self.assertEqual(image.getpixel((128,128))[:3],(255,0,0))
        with Image.open(directory/'frame-02.png') as image:self.assertEqual(image.getpixel((128,128))[:3],(0,0,255))
        self.assertEqual((directory/'frame-01.png').read_bytes(),(directory/'frame-03.png').read_bytes())

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_real_grouped_surface_tracks_and_final_export(self):
        import shutil,asyncio
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root));config.OUTPUTS_DIR.mkdir(parents=True,exist_ok=True)
        value={'title':'Material controls regression','width':360,'height':360,'fps':12,'finishing':{'motion_blur':.6,'samples':3,'grain':.04},'scenes':[{'id':'surface','duration':2,'layers':[
            {'id':'assembly','component':'group','width':.85,'height':.85,'mask':{'kind':'ellipse'},'tracks':{'mask_reveal':[{'time':0,'value':0},{'time':.5,'value':1}]}},
            {'id':'mesh','component':'mesh','parent':'assembly','width':1,'height':1,'props':{'kind':'torus','segments':32,'rings':12,'material':'metal'},'props_tracks':{'roughness':[{'time':0,'value':.7},{'time':2,'value':.12}]},'color_tracks':{'color':[{'time':0,'value':'#d39869'},{'time':2,'value':'#7777bb'}]}},
            {'id':'title','component':'text','y':.1,'height':.15,'props':{'text':'A new surface','size':.055,'mode':'lines'}}]}]}
        fonts=list((config.WEB_DIR/'assets').glob('geist-latin-wght-normal-*.woff2'))
        if fonts:
            attached=self.root/'display.woff2';shutil.copyfile(fonts[0],attached);value['fonts']=[{'id':'attached','source':str(attached)}];value['scenes'][0]['layers'][2]['props']['font']='attached'
        job=render.submit(AnimationRenderRequest(composition=AnimationComposition.model_validate(value),session_id='owner',quality='final'));result=await jobs.wait(job.id)
        self.assertEqual(result.status,'done',result.error)
        report=json.loads((config.OUTPUTS_DIR/'animations'/job.id/'report.json').read_text())
        self.assertEqual(report['quality'],'final');self.assertEqual(report['encoded_frames'],24);self.assertTrue(report['deterministic'])
        self.assertTrue(report['surface_renderer'],report['warnings']);self.assertIn('SwiftShader',report['surface_renderer'])

    @unittest.skipUnless(browser_installed() and media.find('ffmpeg') and media.find('ffprobe'),'Requires a CPU browser and FFmpeg')
    async def test_real_jointed_scene_and_embedded_glb_clip_are_deterministic(self):
        import struct,asyncio
        bus.bind_loop(asyncio.get_running_loop());state.set_root('owner',str(self.root));config.OUTPUTS_DIR.mkdir(parents=True,exist_ok=True)
        values=[-.5,0,0,.5,0,0,0,1,0, 0,1,2, 0,0,0,0,.5,0,0,0,0]
        binary=struct.pack('<'+str(len(values))+'f',*values)
        document={'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0}],'buffers':[{'byteLength':len(binary)}],'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':36},{'buffer':0,'byteOffset':36,'byteLength':12},{'buffer':0,'byteOffset':48,'byteLength':36}],'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3','min':[-.5,0,0],'max':[.5,1,0]},{'bufferView':1,'componentType':5126,'count':3,'type':'SCALAR','min':[0],'max':[2]},{'bufferView':2,'componentType':5126,'count':3,'type':'VEC3'}],'meshes':[{'primitives':[{'attributes':{'POSITION':0},'material':0}]}],'materials':[{'doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.2,.5,.8,1],'metallicFactor':0,'roughnessFactor':.8}}],'animations':[{'name':'Hop','samplers':[{'input':1,'output':2,'interpolation':'LINEAR'}],'channels':[{'sampler':0,'target':{'node':0,'path':'translation'}}]}]}
        body=json.dumps(document).encode();body+=b' '*((-len(body))%4);asset=self.root/'hop.glb'
        asset.write_bytes(struct.pack('<III',0x46546c67,2,28+len(body)+len(binary))+struct.pack('<II',len(body),0x4e4f534a)+body+struct.pack('<II',len(binary),0x004e4942)+binary)
        value=AnimationComposition.model_validate({'title':'Connected assets','width':256,'height':256,'fps':12,'scenes':[{'id':'scene','duration':2,'layers':[{'id':'world','component':'scene3d','width':1,'height':1,'props':{'nodes':[{'id':'joint','kind':'group','tracks':{'ry':[{'time':0,'value':-20},{'time':2,'value':30}]}},{'id':'fixture','kind':'model','parent':'joint','source':str(asset),'clip':'Hop'},{'id':'floor','kind':'plane','dimensions':[20,20,1],'rotation':[-90,0,0],'position':[0,-.02,0],'color':'#cccccc'}],'camera':{'position':[0,2,5],'target':[0,.5,0]}}}]}]})
        job=render.submit(AnimationRenderRequest(composition=value,session_id='owner',quality='final'));result=await jobs.wait(job.id)
        self.assertEqual(result.status,'done',result.error)
        directory=config.OUTPUTS_DIR/'animations'/job.id;report=json.loads((directory/'report.json').read_text())
        self.assertEqual(report['encoded_frames'],24);self.assertTrue(report['deterministic']);self.assertIn('SwiftShader',report['surface_renderer']);self.assertEqual(report['network'],'blocked')
        self.assertTrue((directory/'assets'/'three'/'LICENSE').is_file())


if __name__=='__main__':unittest.main()
