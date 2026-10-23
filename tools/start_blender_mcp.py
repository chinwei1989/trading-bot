import bpy

print("ENABLE", bpy.ops.preferences.addon_enable(module="blender_mcp"))
print("START", bpy.ops.blendermcp.start_server())
bpy.ops.wm.save_userpref()
print("BLENDER_MCP_READY")
